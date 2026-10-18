import sys

if "--self-check" in sys.argv:
    # A packaged build can fail in ways running from source never does: a module the
    # bundler did not notice, an icon that was not copied. The release workflow runs
    # this on every platform because it cannot look at a window.
    from nixync_front.self_check import self_check

    raise SystemExit(self_check())

from nixync_front.app import main

raise SystemExit(main())
