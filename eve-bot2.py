#!/usr/bin/env python
#
#Copyright (c) 2014, Philip Cass <frymaster@127001.org>
#
#All rights reserved.
#
#Redistribution and use in source and binary forms, with or without
#modification, are permitted provided that the following conditions
#are met:
#
#- Redistributions of source code must retain the above copyright notice,
#  this list of conditions and the following disclaimer.
#- Redistributions in binary form must reproduce the above copyright notice,
#  this list of conditions and the following disclaimer in the documentation
#  and/or other materials provided with the distribution.
#- Neither the name of localhost, 127001.org, eve-bot nor the names of its
#  contributors may be used to endorse or promote products derived from this
#  software without specific prior written permission.

#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
#  ``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
#  LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
#  A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE FOUNDATION OR
#  CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
#  EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
#  PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
#  PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
#  LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
#  NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
#  SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

#
#http://frymaster.127001.org/mumble

from mumbleclient import MumbleClient
from mumbleclient import MumbleControlProtocol

import heapq
import time
import sys
import optparse

from twisted.internet import reactor, task

class MimicClient(MumbleClient.AutoChannelJoinClient):

    def ServerSyncReceived(self,message):
        #We may have had voice data waiting to be transmitted.  Prune all
        # voice data set to go out before the current point.
        t=time.time()
        vd = self.settings.voiceData
        while True:
            someFound = False
            try:
                if vd[0][0] < t:
                    someFound = True
                    heapq.heappop(vd)
            except IndexError:
                pass
            if not someFound: break


class ListeningClient(MumbleClient.AutoChannelJoinClient):

    users={}
    mimics={}

    def UserStateReceived(self,message):
        if self.sessionID is not None:
            self.checkSession(message.session)

    def checkSession(self,session):
        user=self.state.users[session]
        if not hasattr(user,"channel_id"): return
        #If the person isn't us or one of our bots,
        if session != self.sessionID and session not in self.mimics:
            #Then, if they're a tracked person
            if session in self.users:
                #Set disconnect True if they aren't in the right channel, and vice versa
                self.users[session].settings._mimic_wantDisconnect=(user.channel_id != self.channelID)
            #If they aren't tracked, and should be, add a mimic
            elif user.channel_id == self.channelID:
                self.addMimic(session)


    def disconnectMimic(self,session):
        mimic = self.users[session]
        del self.users[session]
        mimic.disconnect()

    def checkMimics(self):
        mimicsToRemove=[]
        for i,mimic in self.users.iteritems():
            if mimic.settings._mimic_wantDisconnect:
                if len(mimic.settings.voiceData)==0:
                    mimicsToRemove.append(i)
        for i in mimicsToRemove:
            self.disconnectMimic(i)

    def mimicDisconnected(self,result,mimicObject=None,userSession=None):
        mimic=mimicObject
        #Remove this mimic from the list of mimics
        self.mimics.pop(mimic.sessionID,None)
        #Try to remove this mimic from the list of users
        try:
            curMimic = self.users[userSession]
            if curMimic == mimic: del self.users[userSession]
        except KeyError:
            pass
        if not mimic.settings._mimic_wantDisconnect:
            if mimic.sessionID is not None:
                # We didn't ask it to quit, and it _had_ sucessfully connected, so let's try again
                self.addMimic(userSession,mimic.settings)
        return result

    def addMimic(self,session,settings=None):
        if settings is None:
            s = MumbleClient.MumbleSettings()
            s.voiceData = []
        else:
            s = settings
        orig = self.settings
        s.hostname = orig.hostname
        s.port = orig.port
        s.password = orig.password
        s._autojoin_joinChannel = self.settings._mimic_mimicChannel
        s.nickname = self.getUnusedName(self.settings._mimic_mimicName.replace("{name}",self.state.users[session].name))
        s._mimic_wantDisconnect=False
        mimic = MimicClient(s)
        self.users[session] = mimic
        mimic.clientConnected.addCallback(self.mimicConnected,mimic)
        mimic.clientDisconnected.addBoth(self.mimicDisconnected,mimicObject=mimic,userSession=session)
        mimic.connect()

    def getUnusedName(self,proposedName):
        userNames = set()
        for u in self.state.users:
            user = self.state.users[u]
            try:
                name = user.name
            except AttributeError:
                name = None
            userNames.add(name)
        if proposedName not in userNames: return proposedName
        i=0
        while True:
            tryName = proposedName + str(i)
            if tryName not in userNames: return tryName
            i+i+1

    def mimicConnected(self,result,mimic):
        self.mimics[mimic.sessionID]=mimic
        return result

    def ServerSyncReceived(self,message):
        v = task.deferLater(reactor,0.1,self.sendVoiceData)
        v.addErrback(self.errorCallback)
        for user in self.state.users:
            self.checkSession(user)

    def VoiceMessageReceived(self,prefix,session,data,TCP=False):
        if session in self.users:
            mimic = self.users[session]
            if not mimic.settings._mimic_wantDisconnect:
                heapq.heappush(mimic.settings.voiceData,(time.time()+self.settings._mimic_delayTime,prefix+data))

    def sendVoiceData(self):
        self.checkMimics()
        while True:
            sent=False
            t= time.time()
            nt = t+self.settings._mimic_delayTime
            for a,mimic in self.mimics.iteritems():
                vd = mimic.settings.voiceData
                if len(vd) > 0:
                    if vd[0][0] <= t:
                        b,data = heapq.heappop(vd)
                        mimic.sendVoiceMessage(data)
                        sent=True
                    if len(vd) > 0:
                        if vd[0][0] < nt: nt = vd[0][0]
            if not sent: break
        v = task.deferLater(reactor,nt-t,self.sendVoiceData)
        v.addErrback(self.errorCallback)

    def connectionLost(self,reason):
        if reactor.running: reactor.stop()

def main():
    p = optparse.OptionParser(description='Mumble 1.2 relaybot to relay comms from a match channel to a spectator channel, with a time delay e.g. if watching on a delayed SourceTV server. Full documentation is available at http://frymaster.127001.org/mumble',
                prog='eve-bot2.py',
                version='%prog 2.0',
                usage='\t%prog -e \"Match Channel\" -r \"Spectator Channel\"')

    p.add_option("-e","--eavesdrop-in",help="Channel to eavesdrop in (MANDATORY)",action="store",type="string")
    p.add_option("-r","--relay-to",help="Channel to relay speech to (MANDATORY)",action="store",type="string")
    p.add_option("-s","--server",help="Host to connect to (default %default)",action="store",type="string",default="localhost")
    p.add_option("-p","--port",help="Port to connect to (default %default)",action="store",type="int",default=64738)
    p.add_option("-n","--nick",help="Nickname for the eavesdropper (default %default)",action="store",type="string",default="-Eve-")
    p.add_option("-d","--delay",help="Time to delay speech by in seconds (default %default)",action="store",type="float",default=90)
    p.add_option("-m","--mimic-name",help="Name for mimic-bots; {name} will be replaced by the player's name (default %default)",action="store",type="string",default="Mimic-{name}")
    p.add_option("--password",help="Password for server, if any",action="store",type="string")

    o, arguments = p.parse_args()

    if o.relay_to==None or o.eavesdrop_in==None:
        p.print_help()
        print "\nYou MUST include both an eavesdrop channel to listen to, and a relay channel to relay to"
        sys.exit(1)

    if o.eavesdrop_in=="Root":
        p.print_help()
        print "\nEavesdrop channel cannot be root (or it would briefly attempt to mimic everyone who joined - including mimics)"
        sys.exit(1)

    if o.mimic_name.find("{name}") == -1:
        o.mimic_name = o.mimic_name + "{name}"

    s = MumbleClient.MumbleSettings()
    s._autojoin_joinChannel = o.eavesdrop_in
    s._mimic_mimicChannel = o.relay_to
    s._mimic_mimicName = o.mimic_name
    s._mimic_delayTime = o.delay
    s.nickname = o.nick
    s.hostname = o.server
    s.port = o.port
    s.password = o.password
    eve = ListeningClient(s)
    eve.connect()
    reactor.run()


if __name__ == "__main__":
    main()
