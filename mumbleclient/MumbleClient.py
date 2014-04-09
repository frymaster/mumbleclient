import platform
import time
import collections

from twisted.internet import reactor,defer, task
from twisted.internet.protocol import Factory, Protocol
from twisted.internet.endpoints import SSL4ClientEndpoint
from twisted.internet.ssl import CertificateOptions

import MumbleControlProtocol
import MumbleVoiceProtocol


class _ControlFactory(Factory):

    def __init__(self,client):
        self.mumbleClient=client

    def buildProtocol(self,addr):
        return MumbleControlProtocol.MumbleControlProtocol(self.mumbleClient)


class MumbleSettings(object):
    """
    Object to hold settings passed to a MumbleClient.

    Settings used by the base client are:
        defaults to "localhost".  At this time MumbleClient is ipv4 only
        .port       defaults to 64738
        .nickname   defaults to "MumblePythonBot"
        .password   defaults to "None"
        .SSLOptions By default a new instance of twisted.internet.ssl.CertificateOptions

    You can assign to a custom instance to provide a client certificate
    and/or verify the server certificate. See the twisted documentation for details

    You can pass in implementation-specific settings in this object.  They will be ignored by the base client.
    """

    def __init__(self):
        """
            Sets defaults for all required options.  These can be altered as required, and implementation-specific
            settings added
        """
        self.host="localhost"
        self.port=64738
        self.nickname="MumblePythonBot"
        self.SSLOptions=CertificateOptions()
        self.password=None


class User(object):
    """Stores all information known about a user at this time"""
    pass


class _MumbleState(object):

    def __init__(self):
        self.numTCPPings=0
        self.avgTCPPing=0
        self.users=collections.defaultdict(User)

class Foo(object):
    pass

class MumbleClient(object):
    """
    An object representing a mumble client which uses twisted as an event and network handler.
    This should be inherited and methods overridden or implemented to create specific clients.

    Client life-cycle:

        - Client will connect to TCP control protocol on the specified host and port.
          .controlConnected is a twisted Deferred that will make a callback when this occurs
        - After a sucessfull connection, client will try to send three control messages
          :meth:`versionMessage`, :meth:`authenticationMessage` and
          :meth:`codecVersionMessage` are called in order and the results sent.
          To alter the contents of these messages (assuming no setting exists), it
          is probably easiest to override the function, call the parent to get the
          "base" message, and alter what you wish
        - The server should then send channel and user information
        - The server will then send a ServerSync message. This triggers the
          .clientConnected callback, and the :meth:`ServerSyncReceived`
          method is called.  At this time the .sessionID variable is set
        - Every 5 seconds, the :meth:`pingMessage`: method is called, and
          the message returned sent to the server
        - When the client disconnects, the .clientDisconnected Deferred is
          triggered (probably via errback and not callback) and the
          :meth:`connectionLost` method called.

    In general, the client is informed of activity via method calls. Outside the object, the program is
    informed of (some) activity via the 3 Deferred objects, with more details functionality being the
    responsiblility of the implementer

    In general, if a message Foo is received by the client, the method FooReceived(self,message) will be called.
    See MumbleControlProtocol for a list of MessageTypes.  Some are implemented in this class and can be
    overridden; some are not needed for base functionality but will be called if defined.  The exception is
    the UDPTunnel message, which is one of two possible ways voice data can be received.  In these cases
    the :meth:`VoiceMessageRecieved` function is called whether the voice source was UDP or TCP.

    To tell if a message affects you, compare the message's session (target) or, optionally, actor (source)
    to self.sessionID.  Note that you cannot react to events (cannot send arbitrary messages) until
    just before :meth:`ServerSyncReceived` has been called, which sets sessionID.

    (Note that UDP is not currently supported)

    """

    def __init__(self,settings=None):

        self.sessionID=None
        if settings is None: settings = MumbleSettings()
        self.settings=settings
        self.state=_MumbleState()
        self.clientConnected = defer.Deferred()
        self.clientDisconnected = defer.Deferred()

    def connect(self):
        """
        Asks the client to connect the control protocol

        Returns a deferred which will callback when the connection suceeds.
        This can also be accessed via the controlConnected attribute.
        Note that this only indicates a TCP connection, which might, if the
        client supplies incorrect authentication details, be immediately closed.

        The clientConnected attribute is a Deferred which will return when
        the login phase is complete.

        :return: A Deferred
        """

        self.point=SSL4ClientEndpoint(reactor, self.settings.host, self.settings.port,self.settings.SSLOptions)
        self.controlConnected = self.point.connect(_ControlFactory(self))
        return self.controlConnected

    def _controlMessageReceived(self,type,name,messageObject):
        try:
            f = getattr(self,"_"+name+"Received")
        except AttributeError:
            f=None
        if callable(f): f(messageObject)
        try:
            f = getattr(self,name+"Received")
        except AttributeError:
            f = None
        if callable(f): f(messageObject)

    def _PingReceived(self,message):
        now = int(time.time()*1000000)
        timestamp = message.timestamp
        if timestamp == self.state.lastTCPTimeStamp:
            self.state.avgTCPPing = (now - timestamp) / 1000.0

    def _ServerSyncReceived(self,message):
        self.sessionID=message.session
        self.clientConnected.callback(True)

    def _UserStateReceived(self,message):
        user = self.state.users[message.session]
        for i in message.ListFields():
            name = i[0].name
            value = i[1]
            if name != "actor": setattr(user,name,value)

    def _UserRemoveReceived(self,message):
        self.state.users.pop(message.session,None)

    def _TCPVoiceMessageReceived(self,data):
        prefix,session,data = MumbleVoiceProtocol.decodeAudioMessage(data)
        self.VoiceMessageReceived(prefix,session,data,TCP=True)

    def _unknownMessageReceived(self,type,data):
        pass

    def _connectionMade(self):
        self.state.initialTime=time.time()
        self.sendMessage(self.versionMessage())
        self.sendMessage(self.authenticationMessage())
        self.sendMessage(self.codecVersionMessage())
        self.state.pingTask = task.LoopingCall(self._pingTask)
        self.state.pingTask.start(5.0,now=False)

    def _connectionLost(self,reason):
        self.clientDisconnected.callback(reason)
        self.connectionLost(reason)

    def _pingTask(self):
        self.sendMessage(self.pingMessage())

    def ServerSyncReceived(self,message):
        """
        Called upon receipt of a ServerSync message

        By the time this is called, sessionID will be set to the client's
        session and the clientConnected callback will have completed.

        :param message: A ServerSync message object
        """

    def sendVoiceMessage(self,data):
        """
        Send a voice message via the active voice channel

        :param str data: A stream of bytes

        This will send data either via the TCP control channel or the UDP
        voice channel if the latter is active.  Data should be a stream of
        bytes in mumble's voice format.
        """

        self.controlProtocol.sendVoiceMessage(data)

    def connectionLost(self,reason):
        """
        Called when a connection is lost to the control protocol

        This is called after the clientDisconnected callback is returned.
        Implementors can override this method or listen for the callback,
        depending on use-case
        """
        pass

    def VoiceMessageReceived(self,prefix,session,data,TCP=False):
        """
        Called when voice data is received

        :param str prefix:  The one-byte message header indicating codec type and if this
            was a standard or direct transmission
        :param int session: The session ID of the source of the transmission
        :param str data:    The voice data, consisting of a series of voice frames and
            optionally positional audio at the end

        If you simply wish to output the voice data again, you can call
        sendVoiceMessage and pass in prefix + data as the data.

        Implementors should override this method to process voice data.
        """
        pass

    def sendMessage(self,message):
        """
        Send a control message

        If you call this method with :obj:`None`, it will ignore the call. This
        behavior is so implementers can cancel the sending of an automatic
        message (like Ping) by overriding :meth:`pingMessage` and returning
        None

        :param message: Any kind of TCP control message, or :obj:`None`

        """
        if message is not None: self.controlProtocol.sendMessage(message)

    def versionMessage(self):
        """
        Called by the client to ask what message to send when it should send
        a Version message on initial connect.

        To change the message it's probably easiest to call the superclass
        method and alter the appropriate fields.

        :return: a Version object
        """

        message = MumbleControlProtocol.Version()
        message.release="1.2.5"
        message.version=66053
        message.os=platform.system()
        message.os_version="evebot1.0.2"
        return message

    def authenticationMessage(self):
        """
        Called by the client to ask what message to send when it should send
        an Authenticate message on initial connect.

        To change the message it's probably easiest to call the superclass
        method and alter the appropriate fields.

        :return: an Authenticate object
        """

        message = MumbleControlProtocol.Authenticate()
        message.username=self.settings.nickname
        if self.settings.password is not None: message.password=self.settings.password
        message.celt_versions.append(-2147483637)
        message.celt_versions.append(-2147483632)
        message.opus=True
        return message

    def codecVersionMessage(self):
        """
        Called by the client to ask what message to send when it should send
        a CodecVersion message on initial connect.

        To change the message it's probably easiest to call the superclass
        method and alter the appropriate fields.

        :return: a CodecVersion object
        """

        message = MumbleControlProtocol.CodecVersion()
        message.alpha=-2147483637
        message.beta=0
        message.prefer_alpha=True
        return message

    def pingMessage(self):
        """
        Called by the client to ask what message to send when it should send
        a Ping message every five seconds.

        To change the message it's probably easiest to call the superclass
        method and alter the appropriate fields.

        :return: a Ping object
        """

        message = MumbleControlProtocol.Ping()
        timestamp = int(time.time()*1000000)
        message.timestamp=timestamp
        message.good=0
        message.late=0
        message.lost=0
        message.resync=0
        message.udp_packets=0
        message.tcp_packets=self.state.numTCPPings
        message.udp_ping_avg=0
        message.udp_ping_var=0.0
        message.tcp_ping_avg=self.state.avgTCPPing
        message.tcp_ping_var=0

        self.state.numTCPPings+=1
        self.state.lastTCPTimeStamp=timestamp
        return message

    def disconnect(self):
        """
        Ask the client to disconnect the control channel

        When sucessful, the .clientDisconnected Deferred is triggered (probably via errback and not callback) 

        """
        self.controlProtocol.disconnect()


class AutoChannelJoinClient(MumbleClient):

    def ChannelStateReceived(self,message):
        if message.name==self.settings._autojoin_joinChannel:
            self.channelID = message.channel_id

    def _ServerSyncReceived(self,message):
        super(AutoChannelJoinClient,self)._ServerSyncReceived(message)
        #MumbleClient._ServerSyncReceived(self,message)
        newMessage = MumbleControlProtocol.UserState()
        newMessage.session = self.sessionID
        newMessage.channel_id=self.channelID
        self.sendMessage(newMessage)


if __name__ == '__main__':
    c = MumbleClient()
#    c.connect()
    def stop(reason):
        reactor.stop()
    c.clientDisconnected.addBoth(stop)
    reactor.run()
