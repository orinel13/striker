from app.cli import build_parser


def test_archive_stats_command_exists():
    args = build_parser().parse_args(["archive-stats"])
    assert args.command == "archive-stats"

