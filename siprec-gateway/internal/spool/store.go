package spool

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/binary"
	"fmt"
	"io"
	"os"
)

type Frame struct { Sequence uint64; CapturedAtMS uint64; PCM []byte }
type Store struct { file *os.File; aead cipher.AEAD; pending []Frame; acknowledged uint64 }

func Open(path string, master []byte) (*Store, error) { block, err := aes.NewCipher(master); if err != nil { return nil, err }; aead, err := cipher.NewGCM(block); if err != nil { return nil, err }; file, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR|os.O_APPEND, 0600); if err != nil { return nil, err }; return &Store{file: file, aead: aead}, nil }
func (s *Store) Append(frame Frame) error { nonce := make([]byte, s.aead.NonceSize()); if _, err := io.ReadFull(rand.Reader, nonce); err != nil { return err }; payload := make([]byte, 16+len(frame.PCM)); binary.BigEndian.PutUint64(payload, frame.Sequence); binary.BigEndian.PutUint64(payload[8:], frame.CapturedAtMS); copy(payload[16:], frame.PCM); encrypted := s.aead.Seal(nil, nonce, payload, nil); length := make([]byte, 4); binary.BigEndian.PutUint32(length, uint32(len(nonce)+len(encrypted))); if _, err := s.file.Write(append(length, append(nonce, encrypted...)...)); err != nil { return err }; s.pending = append(s.pending, frame); return s.file.Sync() }
func (s *Store) Acknowledge(sequence uint64) { s.acknowledged = max(s.acknowledged, sequence); kept := s.pending[:0]; for _, frame := range s.pending { if frame.Sequence > s.acknowledged { kept = append(kept, frame) } }; s.pending = kept }
func (s *Store) PendingSequences() []uint64 { values := make([]uint64, 0, len(s.pending)); for _, frame := range s.pending { values = append(values, frame.Sequence) }; return values }
func (s *Store) Close() error { if s.file == nil { return fmt.Errorf("spool already closed") }; err := s.file.Close(); s.file = nil; return err }
func max(a, b uint64) uint64 { if a > b { return a }; return b }
