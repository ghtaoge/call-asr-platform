package tenant

import (
	"errors"
	"fmt"
	"regexp"
	"strings"
)

var ErrRolePending = errors.New("participant roles are ambiguous")

type Participant struct { ID string; Number string }
type Rules struct { Extensions []string }

func (r Rules) Map(participants []Participant) (map[string]string, error) {
	roles := map[string]string{}; internal := 0; external := 0
	for _, participant := range participants { matches := false; for _, pattern := range r.Extensions { if match(pattern, participant.Number) { matches = true; break } }; if matches { roles[participant.ID] = "sales"; internal++ } else { roles[participant.ID] = "customer"; external++ } }
	if len(participants) != 2 || internal != 1 || external != 1 { return nil, ErrRolePending }; return roles, nil
}

func match(pattern, value string) bool { if pattern == "" { return false }; expression := "^" + regexp.QuoteMeta(pattern) + "$"; expression = strings.ReplaceAll(expression, "X", "[0-9]"); ok, _ := regexp.MatchString(expression, value); return ok }

func Validate(pattern string) error { if pattern == "" { return errors.New("extension pattern is empty") }; for _, char := range pattern { if (char < '0' || char > '9') && char != 'X' { return fmt.Errorf("extension pattern contains unsupported character") } }; return nil }
