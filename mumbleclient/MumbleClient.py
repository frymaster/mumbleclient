import MumbleControlProtocol
import MumbleVoiceProtocol

from twisted.internet import reactor,defer, task
from twisted.internet.protocol import Factory, Protocol
from twisted.internet.endpoints import SSL4ClientEndpoint
from twisted.internet.ssl import CertificateOptions

import platform
import time
import collections

class _ControlFactory(Factory):

    def __init__(self,client):
        self.mumbleClient=client

    def buildProtocol(self,addr):
        return MumbleControlProtocol.MumbleControlProtocol(self.mumbleClient)

class MumbleSettings(object):
    host="localhost"
    port=64738
    nickname="MumblePythonBot"
    SSLOptions=CertificateOptions()
    password=None

class User(object):
    pass

class _MumbleState(object):
    numTCPPings=0
    avgTCPPing=0
    users=collections.defaultdict(User)

class MumbleClient(object):

    sessionID=None

    def __init__(self,settings=None):

        if settings is None: settings = MumbleSettings()
        self.settings=settings
        self.state=_MumbleState()

        self.point=SSL4ClientEndpoint(reactor, self.settings.host, self.settings.port,self.settings.SSLOptions)
        deferred = self.point.connect(_ControlFactory(self))
        self.clientConnected = defer.Deferred()
        self.clientDisconnected = defer.Deferred()

    def _controlMessageReceived(self,type,name,messageObject):
        try:
            f = getattr(self,"_"+name+"Received")
            if callable(f): f(messageObject)
        except AttributeError:
            pass
        try:
            f = getattr(self,name+"Received")
            if callable(f): f(messageObject)
        except AttributeError:
            pass

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
        self.TCPVoiceMessageReceived(prefix,session,data,TCP=True)

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

    def sendVoiceMessage(self,data):
        self.controlProtocol.sendVoiceMessage(data)

    def connectionLost(self,reason):
        pass

    def TCPVoiceMessageReceived(self,prefix,session,data,TCP=False):
        pass

    def sendMessage(self,message):
        if message is not None: self.controlProtocol.sendMessage(message)

    def versionMessage(self):
        message = MumbleControlProtocol.Version()
        message.release="1.2.5"
        message.version=66053
        message.os=platform.system()
        message.os_version="evebot1.0.2"
        return message

    def authenticationMessage(self):
        message = MumbleControlProtocol.Authenticate()
        message.username=self.settings.nickname
        if self.settings.password is not None: message.password=self.settings.password
        message.celt_versions.append(-2147483637)
        message.celt_versions.append(-2147483632)
        message.opus=True
        return message

    def codecVersionMessage(self):
        message = MumbleControlProtocol.CodecVersion()
        message.alpha=-2147483637
        message.beta=0
        message.prefer_alpha=True
        return message

    def pingMessage(self):
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
        self.controlProtocol.disconnect()

class AutoChannelJoinClient(MumbleClient):

    def ChannelStateReceived(self,message):
        if message.name==self.settings._autojoin_joinChannel:
            self.channelID = message.channel_id

    def _ServerSyncReceived(self,message):
        MumbleClient._ServerSyncReceived(self,message)
        newMessage = MumbleControlProtocol.UserState()
        newMessage.session = self.sessionID
        newMessage.channel_id=self.channelID
        self.sendMessage(newMessage)

if __name__ == '__main__':
    c = MumbleClient()
    def stop(reason):
        reactor.stop()
    c.clientDisconnected.addBoth(stop)
    reactor.run()
