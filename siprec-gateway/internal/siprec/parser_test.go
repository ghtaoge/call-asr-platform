package siprec

import "testing"

func TestParseInviteExtractsTwoStreamsAndParticipants(t *testing.T) {
	invite := "Content-Type: multipart/mixed; boundary=call\r\n\r\n--call\r\nContent-Type: application/sdp\r\n\r\nm=audio 20000 RTP/AVP 8\r\na=rtpmap:8 PCMA/8000\r\nm=audio 20002 RTP/AVP 0\r\na=rtpmap:0 PCMU/8000\r\n--call\r\nContent-Type: application/rs-metadata+xml\r\n\r\n<recordingSession sessionId=\"rec-1\"><participant id=\"p1\" number=\"1001\"/></recordingSession>\r\n--call--\r\n"
	recording, err := ParseInvite([]byte(invite), Limits{MaxBody: 1 << 20, MaxXMLDepth: 32})
	if err != nil { t.Fatal(err) }; if len(recording.Streams) != 2 || recording.Streams[0].Codec != "PCMA" || recording.SessionID != "rec-1" { t.Fatalf("unexpected recording: %#v", recording) }
}

func TestParseInviteRejectsExternalEntity(t *testing.T) { invite := "Content-Type: multipart/mixed; boundary=x\r\n\r\n--x\r\nContent-Type: application/sdp\r\n\r\nm=audio 1 RTP/AVP 8\r\na=rtpmap:8 PCMA/8000\r\nm=audio 2 RTP/AVP 0\r\na=rtpmap:0 PCMU/8000\r\n--x\r\nContent-Type: application/rs-metadata+xml\r\n\r\n<!DOCTYPE recordingSession [<!ENTITY xxe SYSTEM \"file:///etc/passwd\">]><recordingSession sessionId=\"x\"/>\r\n--x--\r\n"; if _, err := ParseInvite([]byte(invite), Limits{}); err == nil { t.Fatal("expected XXE rejection") } }
