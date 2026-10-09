FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY . .
RUN gofmt -w .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /gateway ./cmd/gateway

FROM alpine:3.20
RUN adduser -D -g '' gateway
USER gateway
WORKDIR /app
COPY --from=build /gateway /app/gateway
EXPOSE 8080
ENV GATEWAY_LISTEN=:8080 \
    GATEWAY_CONFIG_DIR=/etc/gateway
ENTRYPOINT ["/app/gateway"]
