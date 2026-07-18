package spool

import "testing"

func TestAckDeletesOnlyConfirmedFrames(t *testing.T) { store, err := Open(t.TempDir()+"/call.spool", []byte("12345678901234567890123456789012")); if err != nil { t.Fatal(err) }; defer store.Close(); for index := uint64(0); index < 5; index++ { if err := store.Append(Frame{Sequence:index, PCM:[]byte{1,2}}); err != nil { t.Fatal(err) } }; store.Acknowledge(2); got := store.PendingSequences(); if len(got) != 2 || got[0] != 3 || got[1] != 4 { t.Fatalf("unexpected pending: %#v", got) } }
