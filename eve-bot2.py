from mumbleclient import MumbleClient
from mumbleclient import MumbleControlProtocol

import heapq
import time
import sys

from twisted.internet import reactor, task
from twisted.internet import task

class MimicClient(MumbleClient.AutoChannelJoinClient):

    def ServerSyncReceived(self,message):
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
        if self.sessionID is not None:  self.checkSession(message.session)

    def checkSession(self,session):
        #If the person isn't us or one of our bots,
        if session != self.sessionID and session not in self.mimics:
            #Then, if they're a tracked person
            if session in self.users:
                #Set disconnect True if they aren't in the right channel, and vice versa
                self.users[session].settings._mimic_wantDisconnect=(self.state.users[session].channel_id != self.channelID)
            #If they aren't tracked, and should be, add a mimic
            elif self.state.users[session].channel_id == self.channelID:
                self.addMimic(session)


    def disconnectMimic(self,session):
        mimic = self.users[session]
        del self.users[session]
        del self.mimics[mimic.sessionID]
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
        s._autojoin_joinChannel = self.settings._mimic_mimicChannel
        s.nickname = "next-gen-" + self.state.users[session].name
        s._mimic_wantDisconnect=False
        mimic = MimicClient(s)
        self.users[session] = mimic
        mimic.clientConnected.addCallback(self.mimicConnected,mimic)
        mimic.clientDisconnected.addBoth(self.mimicDisconnected,mimicObject=mimic,userSession=session)

    def mimicConnected(self,result,mimic):
        self.mimics[mimic.sessionID]=mimic
        return result

    def ServerSyncReceived(self,message):
        v = task.deferLater(reactor,1,self.sendVoiceData)
        for user in self.state.users:
            self.checkSession(user)

    def TCPVoiceMessageReceived(self,prefix,session,data,TCP=False):
        if session in self.users:
            mimic = self.users[session]
            heapq.heappush(mimic.settings.voiceData,(time.time()+self.settings._mimic_delayTime,prefix+data))

    def sendVoiceData(self):
        self.checkMimics()
        while True:
            sent=False
            t= time.time()
            nt = t+1
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

    def connectionLost(self,reason):
        if reactor.running: reactor.stop()

if __name__ == "__main__":
    s = MumbleClient.MumbleSettings()
    s._autojoin_joinChannel = "TF2 Match #1"
    s._mimic_mimicChannel = "TF2 Match Spec #1"
    s._mimic_delayTime = 90
    s.nickname = "Eve-next-gen"
    a = ListeningClient(s)
    reactor.run()
