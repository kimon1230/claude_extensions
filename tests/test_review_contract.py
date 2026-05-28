"""Structural checks for the shared review output-contract file.

Batch 6 consolidates the genuinely-shared boilerplate of the `/code-review` and
`/security-audit` subagent prompts into `rules/review-output-contract.md`. These
tests pin the consolidation contract: the shared file exists, carries no
severity scale, and each consuming skill references it while keeping its own
domain-specific scale and content.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SHARED = REPO / "rules" / "review-output-contract.md"
CODE_REVIEW = REPO / "skills" / "code-review" / "SKILL.md"
SECURITY_AUDIT = REPO / "skills" / "security-audit" / "SKILL.md"
CRITICAL_REVIEW = REPO / "skills" / "critical-review" / "SKILL.md"

CONSUMERS = (CODE_REVIEW, SECURITY_AUDIT)

# The three fragments the shared file is the single source of truth for.
SCOPE_FRAGMENT = (
    "Read the files in scope. For context, you may read up to 5 additional files"
)
FINDINGS_FRAGMENT = (
    "Return findings as a numbered list, max 10 items, highest severity first. "
    "Each item must have exactly these fields:"
)
CLOSING_FRAGMENT = (
    "Return NO other text, except: if you encounter tool errors or cannot read "
    "required files, report that as your first finding"
)


def test_shared_file_exists():
    assert SHARED.is_file()


def test_shared_file_has_no_severity_scale():
    text = SHARED.read_text()
    assert "critical | major | minor" not in text
    assert "critical | high | medium | low" not in text
    assert "Severity guide" not in text


def test_shared_file_holds_the_three_fragments():
    text = SHARED.read_text()
    assert SCOPE_FRAGMENT in text
    assert FINDINGS_FRAGMENT in text
    assert CLOSING_FRAGMENT in text


def test_consumer_skills_reference_shared_file():
    for skill in CONSUMERS:
        assert "rules/review-output-contract.md" in skill.read_text()


def test_consumer_skills_use_the_fragment_markers():
    for skill in CONSUMERS:
        text = skill.read_text()
        assert "<<shared:scope-and-context>>" in text
        assert "<<shared:findings-format>>" in text
        assert "<<shared:closing-instruction>>" in text


def test_consumer_skills_no_longer_inline_the_shared_fragments():
    # The boilerplate must live only in the shared file, not be duplicated back
    # into the skill prompts — otherwise the consolidation is cosmetic.
    for skill in CONSUMERS:
        text = skill.read_text()
        assert SCOPE_FRAGMENT not in text
        assert FINDINGS_FRAGMENT not in text
        assert CLOSING_FRAGMENT not in text


def test_consumer_skills_keep_their_own_severity_scale():
    assert "critical | major | minor" in CODE_REVIEW.read_text()
    assert "critical | high | medium | low" in SECURITY_AUDIT.read_text()


def test_consumer_skills_keep_their_own_rationalizations_and_red_flags():
    # Domain-specific tuning stays inline and distinct per skill.
    code = CODE_REVIEW.read_text()
    sec = SECURITY_AUDIT.read_text()
    assert "Rationalizations to Reject" in code
    assert "Rationalizations to Reject" in sec
    assert "Red Flags" in code
    assert "Red Flags" in sec
    # A code-quality rationalization must not have leaked into the security skill.
    assert "correctness is necessary but not sufficient" in code
    assert "correctness is necessary but not sufficient" not in sec
    # A security rationalization must not have leaked into the code-review skill.
    assert "internal networks get breached" in sec
    assert "internal networks get breached" not in code


def test_critical_review_does_not_use_the_shared_fragments():
    # /critical-review reviews a plan, not code; its preamble and closer differ,
    # so it intentionally does not consume the shared fragments.
    text = CRITICAL_REVIEW.read_text()
    assert "<<shared:" not in text
    assert "rules/review-output-contract.md" not in text
