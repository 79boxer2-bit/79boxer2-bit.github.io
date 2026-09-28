/**
 * 건축물대장 API 프록시 (Cloudflare Workers, 무료 요금제로 충분)
 *
 * 공공데이터포털 API는 브라우저에서 직접 호출하면 CORS로 막힐 수 있어,
 * 광고 관리 페이지(admin/)가 이 프록시를 거쳐 호출합니다.
 *
 * 설치:
 *  1. https://dash.cloudflare.com → Workers & Pages → Create → "Hello World" 워커 생성
 *  2. 코드 편집에서 이 파일 내용을 붙여 넣고 Deploy
 *  3. 나온 주소(https://OOO.workers.dev)를 광고 관리 페이지 설정의 '건축물대장 프록시 주소'에 입력
 *
 * 건축물대장 조회 경로만 중계하고, 허용한 사이트에서 온 요청만 받습니다.
 */
const ALLOWED_ORIGINS = ["https://79boxer2-bit.github.io"];
const ALLOWED_PATH = /^\/1613000\/BldRgstHubService\/get[A-Za-z]+$/;

export default {
  async fetch(request) {
    const origin = request.headers.get("Origin") || "";
    const cors = {
      "Access-Control-Allow-Origin": ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0],
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Vary": "Origin",
    };
    if (request.method === "OPTIONS") return new Response(null, { headers: cors });
    if (request.method !== "GET" || !ALLOWED_ORIGINS.includes(origin)) {
      return new Response("forbidden", { status: 403, headers: cors });
    }

    const url = new URL(request.url);
    if (!ALLOWED_PATH.test(url.pathname)) {
      return new Response("not found", { status: 404, headers: cors });
    }

    const upstream = await fetch("https://apis.data.go.kr" + url.pathname + url.search);
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { ...cors, "Content-Type": upstream.headers.get("Content-Type") || "application/json" },
    });
  },
};
