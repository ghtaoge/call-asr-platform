package media

import "testing"

func TestJitterBufferOrdersAndDeduplicates(t *testing.T) { buffer := NewJitterBuffer(8); output := []Packet{}; for _, sequence := range []uint16{1,3,2,2,4} { output = append(output, buffer.Push(Packet{Sequence:sequence})...) }; if len(output) != 4 || output[1].Sequence != 2 { t.Fatalf("unexpected packets: %#v", output) } }
func TestPCMAProducesTwentyMillisecond16kPCM(t *testing.T) { samples := make([]int16, 160); decoded := Upsample8To16(samples); if len(decoded) != 320 { t.Fatalf("expected 320 samples, got %d", len(decoded)) } }
