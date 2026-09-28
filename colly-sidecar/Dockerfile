FROM golang:1.22-alpine AS builder

WORKDIR /build
COPY go.mod ./
RUN go mod download || true
COPY . .
RUN go mod tidy && CGO_ENABLED=0 GOOS=linux go build -o /colly-sidecar ./cmd/server

FROM alpine:3.20
RUN apk add --no-cache ca-certificates wget
WORKDIR /app
COPY --from=builder /colly-sidecar /app/colly-sidecar
EXPOSE 8081
ENV COLLY_SIDECAR_HOST=0.0.0.0
ENV COLLY_SIDECAR_PORT=8081
CMD ["/app/colly-sidecar"]
