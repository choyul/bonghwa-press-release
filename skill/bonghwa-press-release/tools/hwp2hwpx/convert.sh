#!/usr/bin/env bash
# 구형 .hwp를 .hwpx로 변환한다. 필요: Java 17+, Maven, git
# 사용법: ./convert.sh 입력.hwp 출력.hwpx
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
IN="$(realpath "$1")"; OUT="$(realpath -m "$2")"

# 1) hwp2hwpx(neolord0, Apache-2.0)는 Maven Central에 없으므로 처음 한 번 받아서 설치한다
if [ ! -d "$HOME/.m2/repository/kr/dogfoot/hwp2hwpx/1.0.0" ]; then
  TMP="$(mktemp -d)"
  git clone -q --depth 1 https://github.com/neolord0/hwp2hwpx.git "$TMP/hwp2hwpx"
  # 테스트 소스의 한글 파일명 때문에 컴파일이 깨지므로 테스트는 건너뛴다
  (cd "$TMP/hwp2hwpx" && mvn -q -B install -Dmaven.test.skip=true \
     -Dmaven.compiler.source=8 -Dmaven.compiler.target=8)
fi

# 2) 변환기 빌드
cd "$HERE"
mvn -q -B compile dependency:build-classpath -Dmdep.outputFile=cp.txt

# 3) Java가 한글 경로를 못 읽는 환경이 있어 영문 임시 경로로 복사해 변환한다
WORK="$(mktemp -d)"
cp "$IN" "$WORK/in.hwp"
java -Dfile.encoding=UTF-8 -cp "target/classes:$(cat cp.txt)" Conv "$WORK/in.hwp" "$WORK/out.hwpx"
cp "$WORK/out.hwpx" "$OUT"
rm -rf "$WORK"
echo "저장: $OUT"
