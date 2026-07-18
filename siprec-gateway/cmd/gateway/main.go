package main

import (
	"log"
	"net/http"
	"os"

	"github.com/gooeto/call-asr-platform/siprec-gateway/internal/config"
	"github.com/gooeto/call-asr-platform/siprec-gateway/internal/health"
)

func main() {
	if len(os.Args) > 1 && os.Args[1] == "--healthcheck" {
		response, err := http.Get("http://127.0.0.1:8081/health")
		if err != nil || response.StatusCode >= 400 { os.Exit(1) }
		return
	}
	cfg, err := config.FromEnv(); if err != nil { log.Fatal(err) }
	state := health.State{Ready: true}; log.Printf("SIPREC gateway configured for %s with RTP %d-%d", cfg.SIPListen, cfg.RTPMin, cfg.RTPMax)
	if err := http.ListenAndServe(":8081", health.Handler(func() health.State { return state })); err != nil { log.Fatal(err) }
}
