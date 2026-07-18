package health

import (
	"encoding/json"
	"net/http"
)

type State struct { Ready bool `json:"ready"`; ActiveCalls int `json:"active_calls"` }

func Handler(state func() State) http.Handler { return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { payload := state(); if !payload.Ready { w.WriteHeader(http.StatusServiceUnavailable) }; _ = json.NewEncoder(w).Encode(payload) }) }
