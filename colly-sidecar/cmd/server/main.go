package main

import (
	"fmt"
	"log"
	"net/http"
	"time"

	"colly-sidecar/internal/config"
	"colly-sidecar/internal/handler"
)

func main() {
	cfg := config.Load()
	defaultTimeout := time.Duration(cfg.Timeout) * time.Second

	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	})
	mux.Handle("/v1/fetch", handler.NewFetchHandler(defaultTimeout))

	addr := fmt.Sprintf("%s:%d", cfg.Host, cfg.Port)
	log.Printf("colly-sidecar listening on %s", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatal(err)
	}
}
