package media

func DecodePCMU(value byte) int16 { value = ^value; sign := value & 0x80; exponent := (value >> 4) & 7; mantissa := value & 15; sample := int16(((int(mantissa)<<3)+132)<<exponent) - 132; if sign != 0 { return -sample }; return sample }

func DecodePCMA(value byte) int16 { value ^= 0x55; sign := value & 0x80; exponent := (value >> 4) & 7; mantissa := value & 15; sample := int16(0); if exponent == 0 { sample = int16((int(mantissa)<<4)+8) } else { sample = int16(((int(mantissa)<<4)+0x108) << (exponent - 1)) }; if sign != 0 { return sample } ; return -sample }

func Upsample8To16(samples []int16) []int16 { if len(samples) == 0 { return nil }; output := make([]int16, 0, len(samples)*2); for index, sample := range samples { output = append(output, sample); if index+1 < len(samples) { output = append(output, int16((int(sample)+int(samples[index+1]))/2)) } else { output = append(output, sample) } }; return output }
