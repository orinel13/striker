from app.cli import build_parser


def test_debug_match_case_command_exists():
    args = build_parser().parse_args(["debug-match-case", "1", "--limit", "5"])
    assert args.case_id == 1
    assert args.limit == 5

