// Homelab patch to Temporal's cmd/server (hosts/stacks/jobs/temporal/build, runbooks/temporal.md "mTLS and
// authorization"): Temporal roles from the verified client certificate.
//
// The frontend requires a client certificate signed by the homelab Temporal CA (requireClientAuth), so the TLS layer
// has already verified the chain. Each certificate names its roles as URI SANs:
//
//	urn:homelab:temporal:system:<reader|writer|admin>
//	urn:homelab:temporal:ns:<namespace>:<reader|writer|admin>
//
// Anything else (no verified chain, other URIs, bearer tokens) gets no role, and Temporal's default authorizer then
// allows only the health check.
package main

import (
	"strings"

	"go.temporal.io/server/common/authorization"
)

const (
	tlsURIClaimMapperName = "homelab-tls-uri"
	tlsURIPrefix          = "urn:homelab:temporal:"
)

type tlsURIClaimMapper struct{}

func newTLSURIClaimMapper() authorization.ClaimMapper { return tlsURIClaimMapper{} }

// AuthInfoRequired: without TLS or a token there is nothing to map (and no role).
func (tlsURIClaimMapper) AuthInfoRequired() bool { return true }

func parseRole(s string) authorization.Role {
	switch s {
	case "reader":
		return authorization.RoleReader
	case "writer":
		return authorization.RoleWriter
	case "admin":
		return authorization.RoleAdmin
	}
	return authorization.RoleUndefined
}

func (tlsURIClaimMapper) GetClaims(ai *authorization.AuthInfo) (*authorization.Claims, error) {
	claims := &authorization.Claims{Namespaces: map[string]authorization.Role{}, AuthType: "mtls"}
	if ai == nil || ai.TLSConnection == nil {
		return claims, nil
	}
	chains := ai.TLSConnection.State.VerifiedChains
	if len(chains) == 0 || len(chains[0]) == 0 {
		return claims, nil
	}
	leaf := chains[0][0]
	claims.Subject = leaf.Subject.CommonName
	for _, u := range leaf.URIs {
		s := u.String()
		if !strings.HasPrefix(s, tlsURIPrefix) {
			continue
		}
		parts := strings.Split(strings.TrimPrefix(s, tlsURIPrefix), ":")
		switch {
		case len(parts) == 2 && parts[0] == "system":
			claims.System |= parseRole(parts[1])
		case len(parts) == 3 && parts[0] == "ns" && parts[1] != "":
			if r := parseRole(parts[2]); r != authorization.RoleUndefined {
				claims.Namespaces[parts[1]] |= r
			}
		}
	}
	return claims, nil
}
