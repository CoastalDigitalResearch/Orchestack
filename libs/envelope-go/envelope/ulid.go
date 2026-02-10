package envelope

import (
	"crypto/rand"
	"encoding/binary"
	"strings"
	"sync"
	"time"
)

// Crockford's Base32 alphabet used by ULID.
const crockfordBase32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

var (
	mu      sync.Mutex
	lastMs  uint64
	lastRnd [10]byte
)

// NewULID generates a ULID string (26 characters, Crockford Base32).
// Monotonic within the same millisecond.
func NewULID() string {
	mu.Lock()
	defer mu.Unlock()

	ms := uint64(time.Now().UnixMilli())

	if ms == lastMs {
		// Increment the random portion to maintain monotonicity.
		incrementRandom(&lastRnd)
	} else {
		lastMs = ms
		_, _ = rand.Read(lastRnd[:])
	}

	var buf [26]byte
	encodeTime(buf[:10], ms)
	encodeRandom(buf[10:], lastRnd)
	return string(buf[:])
}

func encodeTime(dst []byte, ms uint64) {
	dst[0] = crockfordBase32[(ms>>45)&0x1F]
	dst[1] = crockfordBase32[(ms>>40)&0x1F]
	dst[2] = crockfordBase32[(ms>>35)&0x1F]
	dst[3] = crockfordBase32[(ms>>30)&0x1F]
	dst[4] = crockfordBase32[(ms>>25)&0x1F]
	dst[5] = crockfordBase32[(ms>>20)&0x1F]
	dst[6] = crockfordBase32[(ms>>15)&0x1F]
	dst[7] = crockfordBase32[(ms>>10)&0x1F]
	dst[8] = crockfordBase32[(ms>>5)&0x1F]
	dst[9] = crockfordBase32[ms&0x1F]
}

func encodeRandom(dst []byte, rnd [10]byte) {
	// Encode 80 bits (10 bytes) into 16 base32 characters.
	v := binary.BigEndian.Uint64(rnd[:8])
	tail := uint16(rnd[8])<<8 | uint16(rnd[9])

	dst[0] = crockfordBase32[(v>>59)&0x1F]
	dst[1] = crockfordBase32[(v>>54)&0x1F]
	dst[2] = crockfordBase32[(v>>49)&0x1F]
	dst[3] = crockfordBase32[(v>>44)&0x1F]
	dst[4] = crockfordBase32[(v>>39)&0x1F]
	dst[5] = crockfordBase32[(v>>34)&0x1F]
	dst[6] = crockfordBase32[(v>>29)&0x1F]
	dst[7] = crockfordBase32[(v>>24)&0x1F]
	dst[8] = crockfordBase32[(v>>19)&0x1F]
	dst[9] = crockfordBase32[(v>>14)&0x1F]
	dst[10] = crockfordBase32[(v>>9)&0x1F]
	dst[11] = crockfordBase32[(v>>4)&0x1F]

	combined := uint32(v&0xF)<<16 | uint32(tail)
	dst[12] = crockfordBase32[(combined>>15)&0x1F]
	dst[13] = crockfordBase32[(combined>>10)&0x1F]
	dst[14] = crockfordBase32[(combined>>5)&0x1F]
	dst[15] = crockfordBase32[combined&0x1F]
}

func incrementRandom(rnd *[10]byte) {
	for i := 9; i >= 0; i-- {
		rnd[i]++
		if rnd[i] != 0 {
			return
		}
	}
}

// IsValidULID checks whether s looks like a valid 26-character Crockford Base32 ULID.
func IsValidULID(s string) bool {
	if len(s) != 26 {
		return false
	}
	upper := strings.ToUpper(s)
	for _, c := range upper {
		if !strings.ContainsRune(crockfordBase32, c) {
			return false
		}
	}
	return true
}
