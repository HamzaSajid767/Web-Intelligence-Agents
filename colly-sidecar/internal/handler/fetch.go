package handler

import (
	"encoding/json"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/gocolly/colly/v2"
)

const defaultUserAgent = "WebIntelligenceAgent/0.1"

// Cookie represents an HTTP cookie.
type Cookie struct {
	Name  string `json:"name"`
	Value string `json:"value"`
}

// FetchRequest is the JSON body for POST /v1/fetch.
type FetchRequest struct {
	URL              string   `json:"url"`
	TimeoutSeconds   int      `json:"timeout_seconds"`
	FollowRedirects  bool     `json:"follow_redirects"`
	RespectRobotsTxt bool     `json:"respect_robots_txt"`
	Cookies          []Cookie `json:"cookies"`
	UserAgent        string   `json:"user_agent"`
	Proxy            string   `json:"proxy"`
}

// FetchResponse is returned after a fetch attempt.
type FetchResponse struct {
	URL            string   `json:"url"`
	StatusCode     int      `json:"status_code"`
	HTML           string   `json:"html"`
	ContentType    string   `json:"content_type"`
	ResponseTimeMs float64  `json:"response_time_ms"`
	Cookies        []Cookie `json:"cookies"`
	Error          *string  `json:"error"`
}

// FetchHandler serves single-page fetch requests via Colly.
type FetchHandler struct {
	defaultTimeout time.Duration
}

// NewFetchHandler creates a fetch handler with default timeout.
func NewFetchHandler(defaultTimeout time.Duration) *FetchHandler {
	return &FetchHandler{defaultTimeout: defaultTimeout}
}

// ServeHTTP handles POST /v1/fetch.
func (h *FetchHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req FetchRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, FetchResponse{
			StatusCode: http.StatusBadRequest,
			Error:      strPtr("invalid request body"),
		})
		return
	}

	if strings.TrimSpace(req.URL) == "" {
		writeJSON(w, http.StatusBadRequest, FetchResponse{
			StatusCode: http.StatusBadRequest,
			Error:      strPtr("url is required"),
		})
		return
	}

	timeout := h.defaultTimeout
	if req.TimeoutSeconds > 0 {
		timeout = time.Duration(req.TimeoutSeconds) * time.Second
	}

	userAgent := req.UserAgent
	if userAgent == "" {
		userAgent = defaultUserAgent
	}

	start := time.Now()
	result := h.fetch(req.URL, timeout, req.FollowRedirects, req.RespectRobotsTxt, req.Cookies, userAgent, req.Proxy)
	result.ResponseTimeMs = float64(time.Since(start).Milliseconds())

	status := http.StatusOK
	if result.Error != nil && result.StatusCode == 0 {
		status = http.StatusBadGateway
	}
	writeJSON(w, status, result)
}

func (h *FetchHandler) fetch(
	url string,
	timeout time.Duration,
	followRedirects bool,
	respectRobotsTxt bool,
	cookies []Cookie,
	userAgent string,
	proxyURL string,
) FetchResponse {
	var (
		mu         sync.Mutex
		finalURL   string
		statusCode int
		body       string
		contentType string
		outCookies []Cookie
		fetchErr   error
	)

	opts := []colly.CollectorOption{
		colly.UserAgent(userAgent),
		colly.MaxBodySize(10 * 1024 * 1024),
	}
	if !respectRobotsTxt {
		opts = append(opts, colly.IgnoreRobotsTxt())
	}
	c := colly.NewCollector(opts...)
	c.SetRequestTimeout(timeout)

	if strings.TrimSpace(proxyURL) != "" {
		if err := c.SetProxy(proxyURL); err != nil {
			msg := "invalid proxy: " + err.Error()
			return FetchResponse{URL: url, Error: &msg}
		}
	}

	if !followRedirects {
		c.SetRedirectHandler(func(_ *http.Request, _ []*http.Request) error {
			return http.ErrUseLastResponse
		})
	}

	c.OnRequest(func(r *colly.Request) {
		for _, cookie := range cookies {
			r.Headers.Set("Cookie", cookie.Name+"="+cookie.Value)
		}
	})

	c.OnResponse(func(r *colly.Response) {
		mu.Lock()
		defer mu.Unlock()
		finalURL = r.Request.URL.String()
		statusCode = r.StatusCode
		body = string(r.Body)
		contentType = r.Headers.Get("Content-Type")
	})

	c.OnError(func(r *colly.Response, err error) {
		mu.Lock()
		defer mu.Unlock()
		fetchErr = err
		if r != nil {
			finalURL = r.Request.URL.String()
			statusCode = r.StatusCode
			body = string(r.Body)
			contentType = r.Headers.Get("Content-Type")
		}
	})

	if err := c.Visit(url); err != nil {
		mu.Lock()
		defer mu.Unlock()
		if fetchErr == nil {
			fetchErr = err
		}
	}

	mu.Lock()
	defer mu.Unlock()

	resp := FetchResponse{
		URL:         finalURL,
		StatusCode:  statusCode,
		HTML:        body,
		ContentType: contentType,
		Cookies:     outCookies,
	}

	if fetchErr != nil && body == "" {
		msg := fetchErr.Error()
		resp.Error = &msg
	}

	if resp.URL == "" {
		resp.URL = url
	}

	return resp
}

func writeJSON(w http.ResponseWriter, status int, payload FetchResponse) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func strPtr(s string) *string {
	return &s
}
