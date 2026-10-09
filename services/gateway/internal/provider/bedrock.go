package provider

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"agent-assurance/services/gateway/internal/normalize"
)

type BedrockAdapter struct{}

func (a *BedrockAdapter) Name() string { return "bedrock" }

func (a *BedrockAdapter) SupportedParams(op Operation) map[string]struct{} {
	switch op {
	case OpEmbeddings, OpResponses:
		return map[string]struct{}{"model": {}}
	default:
		return map[string]struct{}{
			"model": {}, "messages": {}, "stream": {}, "max_tokens": {}, "max_completion_tokens": {},
			"temperature": {}, "top_p": {}, "tools": {}, "tool_choice": {}, "stop": {},
		}
	}
}

func (a *BedrockAdapter) Invoke(ctx context.Context, req InvokeRequest) (*InvokeResult, error) {
	switch req.Operation {
	case OpChat:
		mapped, err := normalize.BedrockConverseRequest(req.Body, req.Deployment.Model)
		if err != nil {
			return nil, err
		}
		var probe struct {
			Stream bool `json:"stream"`
		}
		_ = json.Unmarshal(req.Body, &probe)
		host := strings.TrimPrefix(strings.TrimPrefix(req.Deployment.Endpoint, "https://"), "http://")
		path := "/model/" + req.Deployment.Model + "/converse"
		if probe.Stream || req.Stream {
			path = "/model/" + req.Deployment.Model + "/converse-stream"
		}
		target := "https://" + host + path
		creds := parseAWSKey(req.APIKey)
		if creds.accessKey == "" {
			return nil, fmt.Errorf("bedrock credential must be ACCESS_KEY:SECRET_KEY[:SESSION]")
		}
		now := time.Now().UTC()
		amzDate := now.Format("20060102T150405Z")
		dateStamp := now.Format("20060102")
		signed := signSigV4("POST", host, path, req.Deployment.Region, "bedrock", amzDate, dateStamp, mapped, creds)
		headers := map[string]string{
			"Authorization":        signed.authorization,
			"X-Amz-Date":           amzDate,
			"X-Amz-Content-Sha256": hex.EncodeToString(sha256Sum(mapped)),
		}
		if creds.sessionToken != "" {
			headers["X-Amz-Security-Token"] = creds.sessionToken
		}
		for k, v := range req.ExtraHeaders {
			headers[k] = v
		}
		resp, err := doUpstream(ctx, http.MethodPost, target, headers, mapped)
		if err != nil {
			return nil, err
		}
		return &InvokeResult{StatusCode: resp.StatusCode, Headers: cloneHeaders(resp.Header), Body: resp.Body}, nil
	case OpResponses, OpEmbeddings:
		return nil, fmt.Errorf("bedrock does not support operation %s", req.Operation)
	default:
		return nil, fmt.Errorf("unsupported operation")
	}
}

type awsCreds struct {
	accessKey, secretKey, sessionToken string
}

func parseAWSKey(raw string) awsCreds {
	parts := strings.Split(raw, ":")
	if len(parts) < 2 {
		return awsCreds{accessKey: raw}
	}
	c := awsCreds{accessKey: parts[0], secretKey: parts[1]}
	if len(parts) > 2 {
		c.sessionToken = parts[2]
	}
	return c
}

type sigV4Result struct {
	authorization string
}

func signSigV4(method, host, path, region, service, amzDate, dateStamp string, payload []byte, cred awsCreds) sigV4Result {
	algorithm := "AWS4-HMAC-SHA256"
	credentialScope := dateStamp + "/" + region + "/" + service + "/aws4_request"
	payloadHash := hex.EncodeToString(sha256Sum(payload))
	canonicalHeaders := "host:" + host + "\n" + "x-amz-content-sha256:" + payloadHash + "\n" + "x-amz-date:" + amzDate + "\n"
	signedHeaders := "host;x-amz-content-sha256;x-amz-date"
	canonicalRequest := strings.Join([]string{
		method, path, "", canonicalHeaders, signedHeaders, payloadHash,
	}, "\n")
	stringToSign := strings.Join([]string{
		algorithm, amzDate, credentialScope, hex.EncodeToString(sha256Sum([]byte(canonicalRequest))),
	}, "\n")
	signingKey := deriveSigningKey(cred.secretKey, dateStamp, region, service)
	signature := hex.EncodeToString(hmacSHA256(signingKey, stringToSign))
	auth := algorithm + " Credential=" + cred.accessKey + "/" + credentialScope +
		", SignedHeaders=" + signedHeaders + ", Signature=" + signature
	return sigV4Result{authorization: auth}
}

func deriveSigningKey(secret, dateStamp, region, service string) []byte {
	kDate := hmacSHA256([]byte("AWS4"+secret), dateStamp)
	kRegion := hmacSHA256(kDate, region)
	kService := hmacSHA256(kRegion, service)
	return hmacSHA256(kService, "aws4_request")
}

func hmacSHA256(key []byte, data string) []byte {
	m := hmac.New(sha256.New, key)
	_, _ = m.Write([]byte(data))
	return m.Sum(nil)
}

func sha256Sum(b []byte) []byte {
	h := sha256.Sum256(b)
	return h[:]
}
