package config

import (
	"os"
	"strconv"
)

// Config holds sidecar server configuration.
type Config struct {
	Host    string
	Port    int
	Timeout int
}

// Load reads configuration from environment variables.
func Load() Config {
	port := 8081
	if v := os.Getenv("COLLY_SIDECAR_PORT"); v != "" {
		if p, err := strconv.Atoi(v); err == nil {
			port = p
		}
	}

	timeout := 20
	if v := os.Getenv("COLLY_SIDECAR_TIMEOUT"); v != "" {
		if t, err := strconv.Atoi(v); err == nil {
			timeout = t
		}
	}

	host := os.Getenv("COLLY_SIDECAR_HOST")
	if host == "" {
		host = "0.0.0.0"
	}

	return Config{
		Host:    host,
		Port:    port,
		Timeout: timeout,
	}
}
