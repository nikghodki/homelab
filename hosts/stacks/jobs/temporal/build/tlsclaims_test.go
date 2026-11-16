package main

import (
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"net/url"
	"testing"

	"go.temporal.io/server/common/authorization"
	"google.golang.org/grpc/credentials"
)

func authInfo(verified bool, uris ...string) *authorization.AuthInfo {
	leaf := &x509.Certificate{Subject: pkix.Name{CommonName: "temporal-test"}}
	for _, s := range uris {
		u, err := url.Parse(s)
		if err != nil {
			panic(err)
		}
		leaf.URIs = append(leaf.URIs, u)
	}
	st := tls.ConnectionState{PeerCertificates: []*x509.Certificate{leaf}}
	if verified {
		st.VerifiedChains = [][]*x509.Certificate{{leaf}}
	}
	return &authorization.AuthInfo{TLSSubject: &leaf.Subject, TLSConnection: &credentials.TLSInfo{State: st}}
}

func TestTLSURIClaims(t *testing.T) {
	m := newTLSURIClaimMapper()
	cases := []struct {
		name   string
		ai     *authorization.AuthInfo
		system authorization.Role
		ns     map[string]authorization.Role
	}{
		{"system admin", authInfo(true, "urn:homelab:temporal:system:admin"), authorization.RoleAdmin, nil},
		{"namespace writer", authInfo(true, "urn:homelab:temporal:ns:ops-agent:writer"), 0,
			map[string]authorization.Role{"ops-agent": authorization.RoleWriter}},
		{"unverified chain gets nothing", authInfo(false, "urn:homelab:temporal:system:admin"), 0, nil},
		{"other URIs ignored", authInfo(true, "spiffe://x/system:admin", "urn:homelab:temporal:system:root",
			"urn:homelab:temporal:ns::admin", "urn:homelab:temporal:ns:a:b:admin"), 0, nil},
		{"no TLS", &authorization.AuthInfo{AuthToken: "Bearer x"}, 0, nil},
		{"nil", nil, 0, nil},
	}
	for _, c := range cases {
		got, err := m.GetClaims(c.ai)
		if err != nil {
			t.Fatalf("%s: %v", c.name, err)
		}
		if got.System != c.system {
			t.Errorf("%s: system role %v, want %v", c.name, got.System, c.system)
		}
		if len(got.Namespaces) != len(c.ns) {
			t.Errorf("%s: namespaces %v, want %v", c.name, got.Namespaces, c.ns)
		}
		for k, v := range c.ns {
			if got.Namespaces[k] != v {
				t.Errorf("%s: namespace %s role %v, want %v", c.name, k, got.Namespaces[k], v)
			}
		}
	}
	// The default authorizer with these claims: a namespace writer can't touch another namespace or the cluster.
	ns, _ := m.GetClaims(authInfo(true, "urn:homelab:temporal:ns:ops-agent:writer"))
	a := authorization.NewDefaultAuthorizer()
	for _, tc := range []struct {
		api, namespace string
		allow          bool
	}{
		{"/temporal.api.workflowservice.v1.WorkflowService/StartWorkflowExecution", "ops-agent", true},
		{"/temporal.api.workflowservice.v1.WorkflowService/StartWorkflowExecution", "homelab", false},
		{"/temporal.api.workflowservice.v1.WorkflowService/TerminateWorkflowExecution", "homelab", false},
		{"/temporal.api.operatorservice.v1.OperatorService/DeleteNamespace", "ops-agent", false},
		{"/temporal.api.workflowservice.v1.WorkflowService/RegisterNamespace", "x", false},
	} {
		r, err := a.Authorize(nil, ns, &authorization.CallTarget{APIName: tc.api, Namespace: tc.namespace})
		if err != nil {
			t.Fatal(err)
		}
		if (r.Decision == authorization.DecisionAllow) != tc.allow {
			t.Errorf("%s on %s: decision %v, want allow=%v", tc.api, tc.namespace, r.Decision, tc.allow)
		}
	}
}
