package config

import (
	"fmt"
	"net"
	"os"
	"strconv"
	"strings"
)

type Config struct {
	SIPListen string
	RTPBindIP string
	PBXAllowlist []*net.IPNet
	RTPMin int
	RTPMax int
	ASRTarget string
	BackendTarget string
	SpoolRoot string
	SpoolKey string
	MaxCalls int
}

func Parse(values map[string]string) (Config, error) {
	get := func(key, fallback string) string { if value := values[key]; value != "" { return value }; return fallback }
	c := Config{SIPListen: get("SIP_LISTEN", "127.0.0.1:5061"), RTPBindIP: get("RTP_BIND_IP", "127.0.0.1"), ASRTarget: values["ASR_TARGET"], BackendTarget: values["BACKEND_TARGET"], SpoolRoot: get("SPOOL_ROOT", "/var/lib/call-asr/spool"), SpoolKey: values["SPOOL_MASTER_KEY"], MaxCalls: 100, RTPMin: 20000, RTPMax: 21999}
	if value := values["MAX_CALLS"]; value != "" { parsed, err := strconv.Atoi(value); if err != nil || parsed < 1 { return Config{}, fmt.Errorf("MAX_CALLS must be positive") }; c.MaxCalls = parsed }
	if len(c.SpoolKey) != 32 { return Config{}, fmt.Errorf("SPOOL_MASTER_KEY must be exactly 32 bytes") }
	allowlist := strings.TrimSpace(values["PBX_ALLOWLIST"])
	if allowlist == "" { return Config{}, fmt.Errorf("PBX_ALLOWLIST is required") }
	for _, cidr := range strings.Split(allowlist, ",") { _, network, err := net.ParseCIDR(strings.TrimSpace(cidr)); if err != nil { return Config{}, fmt.Errorf("invalid PBX_ALLOWLIST: %w", err) }; c.PBXAllowlist = append(c.PBXAllowlist, network) }
	if net.ParseIP(c.RTPBindIP) == nil { return Config{}, fmt.Errorf("RTP_BIND_IP is invalid") }
	return c, nil
}

func FromEnv() (Config, error) { values := map[string]string{}; for _, item := range os.Environ() { pair := strings.SplitN(item, "=", 2); values[pair[0]] = pair[1] }; return Parse(values) }

func (c Config) AllowsPBX(address net.IP) bool { for _, network := range c.PBXAllowlist { if network.Contains(address) { return true } }; return false }
