package tenant

import "testing"

func TestExtensionRuleMapsInternalToSalesAndExternalToCustomer(t *testing.T) { roles, err := (Rules{Extensions: []string{"1XXX"}}).Map([]Participant{{ID:"a", Number:"1001"}, {ID:"b", Number:"13800138000"}}); if err != nil || roles["a"] != "sales" || roles["b"] != "customer" { t.Fatalf("unexpected roles: %#v %v", roles, err) } }
func TestAmbiguousParticipantsRemainUnknown(t *testing.T) { if _, err := (Rules{Extensions: []string{"1XXX"}}).Map([]Participant{{ID:"a", Number:"1001"}, {ID:"b", Number:"1002"}}); err != ErrRolePending { t.Fatalf("expected role pending, got %v", err) } }
