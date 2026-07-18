package media

import "sort"

type Packet struct { Sequence uint16; Timestamp uint32; Payload []byte }
type JitterBuffer struct { max int; packets map[uint16]Packet; next *uint16 }

func NewJitterBuffer(max int) *JitterBuffer { return &JitterBuffer{max: max, packets: map[uint16]Packet{}} }
func (b *JitterBuffer) Push(packet Packet) []Packet { if _, exists := b.packets[packet.Sequence]; exists { return nil }; if len(b.packets) >= b.max { b.flushOldest() }; b.packets[packet.Sequence] = packet; return b.flushContiguous() }
func (b *JitterBuffer) flushContiguous() []Packet { if b.next == nil { sequences := make([]int, 0, len(b.packets)); for sequence := range b.packets { sequences = append(sequences, int(sequence)) }; sort.Ints(sequences); if len(sequences) == 0 { return nil }; first := uint16(sequences[0]); b.next = &first }; output := []Packet{}; for { packet, exists := b.packets[*b.next]; if !exists { break }; output = append(output, packet); delete(b.packets, *b.next); value := *b.next + 1; b.next = &value }; return output }
func (b *JitterBuffer) flushOldest() { sequences := make([]int, 0, len(b.packets)); for sequence := range b.packets { sequences = append(sequences, int(sequence)) }; sort.Ints(sequences); if len(sequences) > 0 { delete(b.packets, uint16(sequences[0])) } }
