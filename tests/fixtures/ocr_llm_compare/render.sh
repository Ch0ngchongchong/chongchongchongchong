#!/bin/sh
# statements/*.html → statements/*.png (Chrome headless 스크린샷)
# 사진처럼 글자 층이 없는 이미지로 만들어 OCR을 실제로 거치게 한다.
# (PDF로 만들면 pdftotext가 글자를 그대로 꺼내 OCR을 건너뛰므로 쓰지 않는다)
# 실행: sh tests/fixtures/ocr_llm_compare/render.sh  (macOS, Google Chrome 필요)
set -e
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
DIR="$(cd "$(dirname "$0")/statements" && pwd)"
for html in "$DIR"/*.html; do
  png="${html%.html}.png"
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars \
    --force-device-scale-factor=2 --window-size=900,1000 \
    --screenshot="$png" "file://$html" >/dev/null 2>&1
  echo "$(basename "$png")"
done
