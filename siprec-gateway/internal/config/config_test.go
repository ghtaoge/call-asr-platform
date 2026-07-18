package config

import "testing"

func TestConfigRejectsPublicRTPWithoutAllowlist(t *testing.T) { _, err := Parse(map[string]string{"SIP_LISTEN":"0.0.0.0:5061", "RTP_BIND_IP":"0.0.0.0", "SPOOL_MASTER_KEY":"12345678901234567890123456789012"}); if err == nil { t.Fatal("expected PBX_ALLOWLIST error") } }
