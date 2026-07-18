package siprec

import (
	"bufio"
	"bytes"
	"encoding/xml"
	"fmt"
	"io"
	"mime"
	"mime/multipart"
	"net/mail"
	"strconv"
	"strings"
)

type Limits struct { MaxBody int64; MaxXMLDepth int }
type Stream struct { ID string; Codec string; PayloadType int; Address string; Port int }
type Participant struct { ID string; Number string }
type Recording struct { SessionID string; Streams []Stream; Participants []Participant }

func ParseInvite(data []byte, limits Limits) (Recording, error) {
	if limits.MaxBody == 0 { limits.MaxBody = 1 << 20 }; if int64(len(data)) > limits.MaxBody { return Recording{}, fmt.Errorf("body too large") }
	message, err := mail.ReadMessage(bufio.NewReader(bytes.NewReader(data))); if err != nil { return Recording{}, fmt.Errorf("malformed SIP message: %w", err) }
	contentType := message.Header.Get("Content-Type"); mediaType, params, err := mime.ParseMediaType(contentType); if err != nil || !strings.HasPrefix(mediaType, "multipart/") { return Recording{}, fmt.Errorf("unsupported media type") }
	body, err := io.ReadAll(io.LimitReader(message.Body, limits.MaxBody+1)); if err != nil || int64(len(body)) > limits.MaxBody { return Recording{}, fmt.Errorf("body too large") }
	reader := multipartReader(mediaType, params, body); if reader == nil { return Recording{}, fmt.Errorf("invalid multipart body") }
	var recording Recording
	for { part, nextErr := reader.NextPart(); if nextErr == io.EOF { break }; if nextErr != nil { return Recording{}, fmt.Errorf("invalid multipart body: %w", nextErr) }; partBody, readErr := io.ReadAll(io.LimitReader(part, limits.MaxBody+1)); if readErr != nil { return Recording{}, readErr }; partType, _, _ := mime.ParseMediaType(part.Header.Get("Content-Type")); switch partType { case "application/sdp": streams, parseErr := parseSDP(string(partBody)); if parseErr != nil { return Recording{}, parseErr }; recording.Streams = streams; case "application/rs-metadata+xml", "application/xml": metadata, parseErr := parseMetadata(partBody, limits.MaxXMLDepth); if parseErr != nil { return Recording{}, parseErr }; recording.SessionID = metadata.SessionID; recording.Participants = metadata.Participants } }
	if recording.SessionID == "" { return Recording{}, fmt.Errorf("recording session id is required") }; if len(recording.Streams) != 2 { return Recording{}, fmt.Errorf("exactly two audio streams are required") }; return recording, nil
}

func multipartReader(mediaType string, params map[string]string, body []byte) *multipart.Reader { boundary := params["boundary"]; if boundary == "" { return nil }; return multipart.NewReader(bytes.NewReader(body), boundary) }

func parseSDP(value string) ([]Stream, error) { streams := []Stream{}; current := Stream{}; for _, line := range strings.Split(value, "\n") { line = strings.TrimSpace(line); if strings.HasPrefix(line, "m=audio ") { if current.ID != "" { streams = append(streams, current) }; fields := strings.Fields(line); if len(fields) < 4 { return nil, fmt.Errorf("malformed audio SDP") }; port, _ := strconv.Atoi(fields[1]); current = Stream{ID:fmt.Sprintf("stream-%d", len(streams)+1), Port:port} } else if strings.HasPrefix(line, "a=rtpmap:") { fields := strings.Fields(strings.TrimPrefix(line, "a=rtpmap:")); if len(fields) != 2 { continue }; payload, _ := strconv.Atoi(fields[0]); codec := strings.ToUpper(strings.Split(fields[1], "/")[0]); if codec != "PCMA" && codec != "PCMU" { return nil, fmt.Errorf("unsupported codec %s", codec) }; current.PayloadType = payload; current.Codec = codec } }; if current.ID != "" { streams = append(streams, current) }; return streams, nil }

type metadata struct { XMLName xml.Name `xml:"recordingSession"`; SessionID string `xml:"sessionId,attr"`; Participants []Participant `xml:"participant"` }
func parseMetadata(value []byte, maxDepth int) (metadata, error) { if bytes.Contains(bytes.ToUpper(value), []byte("<!DOCTYPE")) || bytes.Contains(bytes.ToUpper(value), []byte("<!ENTITY")) { return metadata{}, fmt.Errorf("external entity is forbidden") }; decoder := xml.NewDecoder(bytes.NewReader(value)); depth := 0; for { token, err := decoder.Token(); if err == io.EOF { break }; if err != nil { return metadata{}, fmt.Errorf("invalid metadata: %w", err) }; switch token.(type) { case xml.StartElement: depth++; if maxDepth > 0 && depth > maxDepth { return metadata{}, fmt.Errorf("metadata depth exceeded") }; case xml.EndElement: depth-- } }; var result metadata; if err := xml.Unmarshal(value, &result); err != nil { return metadata{}, err }; return result, nil }
