const API = "";

async function apiGet(path) {
  const res = await fetch(API + path);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function apiPost(path, body) {
  const res = await fetch(API + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
}

function formatRs(n) {
  if (n === null || n === undefined) return "-";
  return "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function statusBadgeClass(status) {
  if (status === "open") return "badge-open";
  if (status === "partially_sold") return "badge-partial";
  return "badge-sold";
}
