package provider

import (
	"fmt"
	"net/url"
	"strings"
)

const defaultAzureAPIVersion = "2024-02-15-preview"

// AzureChatURL builds a single chat/completions URL with deployment path and api-version.
func AzureChatURL(endpoint, deployment, apiVersion string) (string, error) {
	return azureOpURL(endpoint, deployment, apiVersion, "chat/completions")
}

func AzureEmbeddingsURL(endpoint, deployment, apiVersion string) (string, error) {
	return azureOpURL(endpoint, deployment, apiVersion, "embeddings")
}

func AzureResponsesURL(endpoint, deployment, apiVersion string) (string, error) {
	return azureOpURL(endpoint, deployment, apiVersion, "responses")
}

func azureOpURL(endpoint, deployment, apiVersion, opPath string) (string, error) {
	if apiVersion == "" {
		apiVersion = defaultAzureAPIVersion
	}
	u, err := url.Parse(strings.TrimRight(endpoint, "/"))
	if err != nil {
		return "", err
	}
	path := u.Path
	if !strings.Contains(path, "/deployments/") {
		if deployment == "" {
			return "", fmt.Errorf("azure deployment name required")
		}
		path = strings.TrimRight(path, "/") + "/openai/deployments/" + url.PathEscape(deployment) + "/" + opPath
	} else if !strings.HasSuffix(path, "/"+opPath) {
		path = strings.TrimRight(path, "/") + "/" + opPath
	}
	u.Path = path
	q := u.Query()
	if q.Get("api-version") == "" {
		q.Set("api-version", apiVersion)
	}
	u.RawQuery = q.Encode()
	return u.String(), nil
}

func AzureAPIVersionFromEndpoint(endpoint string) string {
	u, err := url.Parse(endpoint)
	if err != nil {
		return defaultAzureAPIVersion
	}
	if v := u.Query().Get("api-version"); v != "" {
		return v
	}
	return defaultAzureAPIVersion
}
