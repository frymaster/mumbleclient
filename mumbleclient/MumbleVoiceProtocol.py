import sys

def decodePDSInt(m,si=0):
    """
    Decodes a PDS int
    Takes a sequence of bytes and optionally a starting position and decodes
    it as if it contains a PDS integer. The return values are the integer,
    and the number of bytes the integer was stored in, as PDS ints can be of
    variable length.  The original starting position plus the length will be
    the start of the next piece of data in the byte sequence
    """
    v = ord(m[si])
    if ((v & 0x80) == 0x00):
        return ((v & 0x7F),1)
    elif ((v & 0xC0) == 0x80):
        return ((v & 0x3F) << 8 | ord(m[si+1]),2)
    elif ((v & 0xF0) == 0xF0):
        if ((v & 0xFC) == 0xF0):
            return (ord(m[si+1]) << 24 | ord(m[si+2]) << 16 | ord(m[si+3]) << 8 | ord(m[si+4]),5)
        elif ((v & 0xFC) == 0xF4):
            return (ord(m[si+1]) << 56 | ord(m[si+2]) << 48 | ord(m[si+3]) << 40 | ord(m[si+4]) << 32 | ord(m[si+5]) << 24 | ord(m[si+6]) << 16 | ord(m[si+7]) << 8 | ord(m[si+8]),9)
        elif ((v & 0xFC) == 0xF8):
            result,length=decodePDSInt(m,si+1)
            return(-result,length+1)
        elif ((v & 0xFC) == 0xFC):
            return (-(v & 0x03),1)
        else:
            print time.strftime("%a, %d %b %Y %H:%M:%S +0000"),"Help Help, out of cheese :("
            sys.exit(1)
    elif ((v & 0xF0) == 0xE0):
        return ((v & 0x0F) << 24 | ord(m[si+1]) << 16 | ord(m[si+2]) << 8 | ord(m[si+3]),4)
    elif ((v & 0xE0) == 0xC0):
        return ((v & 0x1F) << 16 | ord(m[si+1]) << 8 | ord(m[si+2]),3)
    else:
        print time.strftime("%a, %d %b %Y %H:%M:%S +0000"),"out of cheese?"
        sys.exit(1)

def decodeAudioMessage(message):
    prefix=message[0]
    session,sessLen=decodePDSInt(message,1)
    data=message[1+sessLen:]
    getAudioFrames(data)
    return prefix,session,data

# Speex/celt only, not OPUS. WIP
def getAudioFrames(data):
    audioFrames=[]
    sequence,length = decodePDSInt(data,0)
    position = length
    lastPacket=False
    print sequence,len(data),position
    while position < len(data) and not lastPacket:
        frameLen = ord(data[position])
        print frameLen,
        if frameLen>127:
            frameLen=frameLen-127
        else:
            lastPacket=True
        print lastPacket,
        frame = data[position + 1:position+frameLen+1]
        audioFrames.append(frame)
        position = position + 1 + frameLen
    position=None   #Don't decode that yet, makes my brain hurt
    return sequence,audioFrames,position
