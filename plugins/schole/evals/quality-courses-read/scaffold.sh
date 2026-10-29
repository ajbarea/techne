#!/bin/bash
set -euo pipefail
cat > sweep.txt <<'EOF'
site https://courses.example.test window 2026-10-28 08:00 to 2026-10-29 08:00 America/New_York
OK CSCI-739 :: news 1 topics 2 dropbox 2
APIFAIL SWEN-755 :: news:404
OK CISC-810 :: news 0 topics 0 dropbox 1
ANNOUNCE CSCI-739 :: Room change for Thursday :: 2026-10-28 15:02 :: Thursday's lecture moves to GOL-2400.
CONTENT CSCI-739 :: Lecture 18 slides :: 2026-10-28 16:10 :: UNREAD
CONTENT CSCI-739 :: Reading list :: 2026-10-28 09:30 :: seen
DUE CSCI-739 :: Assignment 4 :: 2026-10-30 23:59
DUE CISC-810 :: Reflection 6 :: 2026-11-03 23:59
PASTDUE CSCI-739 :: Quiz 7 :: 2026-10-28 23:59 :: NOT SUBMITTED
PASTDUE CISC-810 :: Peer review 3 :: 2026-10-28 17:00 :: NOROW
EOF
