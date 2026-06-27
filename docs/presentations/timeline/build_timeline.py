#!/usr/bin/env python3
"""Render a Dark-Factory-style feature-timeline deck from a master JSON dataset.

Reusable: point --data at df-timeline-master.json (or, later, a markethawk one) and
it emits a self-contained HTML slide deck using the dark-factory-v2 palette + slide
engine. The centerpiece is a master rail: every feature a color-coded node on its
subsystem lane, with an era ribbon, epic bands, an interactive legend filter, and
hover tooltips. Plus scars + in-flight/roadmap slides.
"""
import argparse, json, html
from datetime import date

GH = "https://github.com/omniscient/markethawk/issues/"

# lane display order (top -> bottom): decides / builds / judges / learns / measures / runs
LANE_ORDER = ["scheduler", "pipeline", "gates", "sdd", "obs", "infra"]

PAD = 2.6  # percent inset on each side of the plot so edge nodes breathe


def d(s):
    y, m, dd = (int(x) for x in s.split("-"))
    return date(y, m, dd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    with open(a.data, "r", encoding="utf-8") as f:
        D = json.load(f)

    meta, subs, eras, epics = D["meta"], D["subsystems"], D["eras"], D["epics"]
    feats, scars, inflight = D["features"], D["scars"], D["in_flight"]

    start, end = d(meta["date_range"][0]), d(meta["date_range"][1])
    span = (end - start).days

    def xpct(dt):
        return PAD + ((dt - start).days / span) * (100 - 2 * PAD)

    # ---- counts per subsystem (for legend) ----
    counts = {k: 0 for k in subs}
    for ft in feats:
        counts[ft["subsystem"]] = counts.get(ft["subsystem"], 0) + 1

    # ---- build nodes per lane with vertical fanning for same-date collisions ----
    def fan(n):
        if n <= 1:
            return [0]
        step = 15
        # symmetric around 0
        mid = (n - 1) / 2
        return [round((i - mid) * step) for i in range(n)]

    lanes_html = []
    for lane in LANE_ORDER:
        s = subs[lane]
        lane_feats = [ft for ft in feats if ft["subsystem"] == lane]
        lane_feats.sort(key=lambda ft: ft["date"])
        # group by date for fanning
        by_date = {}
        for ft in lane_feats:
            by_date.setdefault(ft["date"], []).append(ft)
        nodes = []
        for ds, group in by_date.items():
            offsets = fan(len(group))
            for ft, off in zip(group, offsets):
                x = xpct(d(ds))
                ref = ft["refs"][0] if ft.get("refs") else ""
                issue = ref[1:] if ref.startswith("#") and ref[1:].isdigit() else ""
                cls = "node " + ft["significance"]
                if ft.get("marquee"):
                    cls += " marquee"
                title = html.escape(ft["title"])
                desc = html.escape(ft["one_line"])
                reflabel = html.escape(" · ".join(ft["refs"])) if ft.get("refs") else ""
                # Windows strftime has no %-d; format the day manually
                pretty = "%s %d" % (d(ds).strftime("%b"), d(ds).day)
                attrs = (
                    'class="%s" data-sub="%s" style="left:%.2f%%;--off:%dpx"'
                    ' data-title="%s" data-date="%s" data-ref="%s" data-desc="%s"'
                    % (cls, lane, x, off, title, pretty, reflabel, desc)
                )
                lbl = '<span class="nlabel">%s</span>' % title
                if issue:
                    nodes.append(
                        '<a href="%s%s" target="_blank" rel="noopener" %s>%s</a>'
                        % (GH, issue, attrs, lbl)
                    )
                else:
                    nodes.append('<button type="button" %s>%s</button>' % (attrs, lbl))
        lanes_html.append(
            '<div class="lane" data-sub="%s">'
            '<div class="lanelabel"><span class="sw" style="background:%s"></span>%s'
            '<span class="lc">%d</span></div>'
            '<div class="lanetrack">%s</div></div>'
            % (lane, s["color"], html.escape(s["label"]), counts[lane], "".join(nodes))
        )

    # ---- era ribbon (top) ----
    era_bounds = [d(e["span_start"]) if "span_start" in e else None for e in eras]
    # derive boundaries from era start dates: each era runs to the next era's start
    starts = [d(s) for s in ["2026-05-02", "2026-05-11", "2026-05-23", "2026-06-03", "2026-06-19"]]
    ends = starts[1:] + [end]
    era_segs = []
    era_tints = ["rgba(255,138,61,.07)", "rgba(63,224,200,.06)", "rgba(255,192,138,.06)",
                 "rgba(84,209,138,.07)", "rgba(167,139,250,.07)"]
    for i, e in enumerate(eras):
        l = xpct(starts[i])
        w = xpct(ends[i]) - l
        era_segs.append(
            '<div class="eseg" style="left:%.2f%%;width:%.2f%%;background:%s">'
            '<span class="en">%s</span><span class="es">%s</span></div>'
            % (l, w, era_tints[i % len(era_tints)], html.escape(e["name"]), html.escape(e["span"]))
        )

    # ---- epic bands (behind lanes) ----
    epic_spans = {"#262": ("2026-06-07", "2026-06-11"),
                  "#340": ("2026-06-11", "2026-06-14"),
                  "#548": ("2026-06-19", "2026-06-26")}
    epic_bands = []
    for ep in epics:
        sd, ed = epic_spans.get(ep["ref"], (None, None))
        if not sd:
            continue
        l = xpct(d(sd))
        w = xpct(d(ed)) - l
        epic_bands.append(
            '<div class="eband" style="left:%.2f%%;width:%.2f%%">'
            '<span class="ebl">EPIC %s</span></div>'
            % (l, w, html.escape(ep["ref"]))
        )

    # ---- axis ticks (weekly) ----
    ticks = []
    cur = start
    tickdates = []
    while cur <= end:
        tickdates.append(cur)
        nxt = date.fromordinal(cur.toordinal() + 7)
        cur = nxt
    if tickdates[-1] != end:
        tickdates.append(end)
    for t in tickdates:
        x = xpct(t)
        lbl = "%s %d" % (t.strftime("%b"), t.day)
        ticks.append('<div class="tick" style="left:%.2f%%"><span>%s</span></div>' % (x, lbl))

    # ---- legend chips ----
    chips = []
    for k in LANE_ORDER:
        s = subs[k]
        chips.append(
            '<button class="chip" data-sub="%s"><span class="sw" style="background:%s"></span>'
            '%s<span class="lc">%d</span></button>'
            % (k, s["color"], html.escape(s["label"]), counts[k])
        )

    # ---- stat row for title ----
    stats = [
        (str(meta["feature_count"]), "features shipped"),
        ("6", "subsystems"),
        ("3", "epics"),
        (str(len(scars)), "self-inflicted scars, all fixed"),
        ("8", "weeks, May 2 → Jun 26"),
    ]
    stat_html = "".join(
        '<div class="stat r" style="--d:%d"><div class="sv">%s</div><div class="sl">%s</div></div>'
        % (260 + i * 70, html.escape(v), html.escape(l)) for i, (v, l) in enumerate(stats)
    )

    # ---- scars cards ----
    scar_cards = []
    for sc in scars:
        ref = html.escape(" · ".join(sc["refs"]))
        scar_cards.append(
            '<div class="scard"><div class="sh"><span class="sd">%s</span>'
            '<span class="sr">%s</span></div><div class="st">%s</div>'
            '<p>%s</p></div>'
            % (html.escape("%s %d" % (d(sc["date"]).strftime("%b"), d(sc["date"]).day)),
               ref, html.escape(sc["title"]), html.escape(sc["one_line"]))
        )

    # ---- in-flight cards ----
    fly_cards = []
    for fl in inflight:
        s = subs[fl["subsystem"]]
        issue = fl["ref"][1:] if fl["ref"].startswith("#") else ""
        fly_cards.append(
            '<a class="fcard" href="%s%s" target="_blank" rel="noopener" style="--ac:%s">'
            '<div class="fh"><span class="fr">%s</span></div>'
            '<div class="ft">%s</div><p>%s</p></a>'
            % (GH, issue, s["color"], html.escape(fl["ref"]),
               html.escape(fl["title"]), html.escape(fl["one_line"]))
        )

    # ===== assemble slides =====
    title_slide = (
        '<section class="slide" data-sec="">'
        '<div class="title-wrap max">'
        '<div class="ember" style="left:10%;width:6px;height:6px;animation-delay:.2s"></div>'
        '<div class="ember" style="left:18%;width:4px;height:4px;animation-delay:1.4s"></div>'
        '<div class="ember" style="left:27%;width:5px;height:5px;animation-delay:2.6s"></div>'
        '<div class="kicker r"><span class="dot"></span>Autonomous Engineering · Feature Timeline</div>'
        '<h1 class="r" style="--d:80">The <span class="am">Dark Factory</span></h1>'
        f'<p class="lead r" style="--d:200; margin-top:1.1rem">{html.escape(meta["subtitle"])}</p>'
        f'<div class="statrow">{stat_html}</div>'
        '<div class="r tiny" style="--d:640; margin-top:2rem; font-family:var(--mono); letter-spacing:.06em">'
        'press <span class="am">→</span> for the timeline · <span class="am">O</span> overview · '
        '<span class="am">N</span> notes</div>'
        '</div></section>'
    )

    rail_slide = (
        '<section class="slide railslide" data-sec="THE ARC · MAY 2 – JUN 26">'
        '<div class="railwrap max">'
        '<div class="railhead">'
        '<h2 class="r">One spec → a self-governing factory <span class="cy">in 54 features</span></h2>'
        '<div class="legend r" style="--d:120">%s'
        '<button class="chip clear" data-sub="">reset</button>'
        '<button class="chip lbl" id="lblbtn">Labels: off</button></div>'
        '</div>'
        '<div class="eras r" style="--d:200">%s</div>'
        '<div class="railplot r" style="--d:260" id="plot">'
        '<div class="overlay">%s%s</div>'
        '<div class="lanes">%s</div>'
        '</div>'
        '<div class="axis">%s</div>'
        '<div class="raillegend tiny">● size = significance · '
        '<span class="am">foundational/marquee</span> ringed · click a node → its GitHub issue · '
        'click a subsystem to isolate its thread · <span class="am">Labels</span> toggles inline names</div>'
        '</div>'
        '<div id="tip" class="tip"></div>'
        '</section>'
        % ("".join(chips), "".join(era_segs), "".join(epic_bands), "".join(ticks),
           "".join(lanes_html), "".join(ticks))
    )

    scars_slide = (
        '<section class="slide" data-sec="RESILIENCE · SELF-REPAIR">'
        '<div class="max">'
        '<div class="kicker r"><span class="dot"></span>The factory fixing itself</div>'
        '<h2 class="r" style="--d:60">Scars <span class="rd">—</span> regressions it introduced, then closed</h2>'
        '<p class="lead r" style="--d:120; margin-bottom:1.2rem">Autonomy means owning your own mistakes. '
        'Each of these was a self-inflicted break the factory diagnosed and repaired — feedstock for the '
        '<span class="em">failure-to-eval flywheel</span>.</p>'
        '<div class="scargrid r" style="--d:200">%s</div>'
        '</div></section>'
        % "".join(scar_cards)
    )

    fly_slide = (
        '<section class="slide" data-sec="ROADMAP · IN FLIGHT">'
        '<div class="max">'
        '<div class="kicker r"><span class="dot"></span>Open at the time of writing</div>'
        '<h2 class="r" style="--d:60">In flight <span class="cy">— what\'s next</span></h2>'
        '<p class="lead r" style="--d:120; margin-bottom:1.2rem">The arc doesn\'t stop. These are the '
        'live tickets pushing the factory further toward hands-off operation.</p>'
        '<div class="flygrid r" style="--d:200">%s</div>'
        '</div></section>'
        % "".join(fly_cards)
    )

    epic_rows = "".join(
        '<div class="eprow r" style="--d:%d"><span class="epref">%s</span>'
        '<span class="epname">%s</span><span class="epclosed">%s</span>'
        '<p>%s</p></div>'
        % (200 + i * 90, html.escape(ep["ref"]), html.escape(ep["name"]),
           html.escape("closed " + ep["closed"]), html.escape(ep["theme"]))
        for i, ep in enumerate(epics)
    )
    close_slide = (
        '<section class="slide" data-sec="SYNTHESIS">'
        '<div class="max">'
        '<div class="kicker r"><span class="dot"></span>The planning spine</div>'
        '<h2 class="r" style="--d:60">Three epics carried the build-out</h2>'
        '<div class="epics">%s</div>'
        '<p class="lead r" style="--d:520; margin-top:1.6rem">From a single design spec to a factory that '
        '<span class="am">refines</span>, <span class="gr">gates</span>, <span class="cy">ships</span>, and '
        '<span class="vi">repairs itself</span> — in eight weeks. The human moved from author to '
        '<span class="em">gatekeeper</span>.</p>'
        '</div></section>'
        % epic_rows
    )

    slides = title_slide + rail_slide + scars_slide + fly_slide + close_slide

    notes_js = {
        0: "The whole arc in one deck: 54 factory/scheduler features over 8 weeks. This is the infrastructure timeline — the MarketHawk product timeline is a separate deck.",
        1: "The centerpiece wall-chart. Six subsystem lanes, time on X. Walk left to right: Genesis lands everything at once (May 2), then the scheduler and refinement give it autonomy, then the huge gate-and-memory build-out in June, then autopilot. Point out the epic bands (#262/#340/#548) and let people click a subsystem to isolate its thread.",
        2: "The honesty slide. The factory repeatedly broke itself and fixed itself — OR-join skips, silent when: discard, the Python-3.14 dep break. Frame these as the input to the self-improvement flywheel, not as embarrassments.",
        3: "Where it's heading: Hermes daemon patterns, session-window-aware backoff, autofix hardening. Autonomy inside the gates keeps deepening.",
        4: "Close on the spine: #262 hardened the loop, #340 made it measurable, #548 made it self-governing. The one-line takeaway: the human moved from author to gatekeeper.",
    }

    out = (
        HEAD + CSS + "</head>\n<body>\n"
        '<div class="wm"><span class="b"></span> The Dark Factory · Timeline</div>\n'
        '<div id="seclabel"></div>\n'
        '<div id="deck">\n' + slides + "\n</div>\n"
        '<button class="navbtn" id="prev" aria-label="previous">‹</button>\n'
        '<button class="navbtn" id="next" aria-label="next">›</button>\n'
        '<div id="progress"><div id="bar"></div></div>\n'
        '<div id="hud"><b id="cur">01</b> / <span id="tot">00</span></div>\n'
        '<div class="hint"><span>← →</span> navigate · <span>O</span> overview · <span>N</span> notes · <span>F</span> full</div>\n'
        '<div id="overview"></div>\n'
        '<div id="notes"><div class="lab">Speaker notes</div><p id="notetext"></p></div>\n'
        "<script>\nconst NOTES = " + json.dumps(notes_js) + ";\n" + JS + "\n</script>\n"
        "</body>\n</html>\n"
    )

    with open(a.out, "w", encoding="utf-8") as f:
        f.write(out)
    print("wrote", a.out, "(%d bytes)" % len(out))


HEAD = '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n' \
       '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n' \
       '<title>The Dark Factory — Feature Timeline</title>\n'

CSS = r"""<style>
  :root{
    --bg:#0a0b0e; --bg2:#0e1015; --panel:#13151d; --panel2:#181b24;
    --line:rgba(255,255,255,.08); --line2:rgba(255,255,255,.14);
    --ink:#eceef3; --mut:#9aa0ad; --mut2:#6b7280;
    --amber:#ff8a3d; --amber-hot:#ff6a1a; --amber-soft:#ffc08a;
    --cyan:#3fe0c8; --cyan-soft:#8af0e2;
    --green:#54d18a; --red:#ff6b6b; --violet:#a78bfa;
    --mono:ui-monospace,"Cascadia Code","SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
    --sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    --grad:linear-gradient(135deg,var(--amber-hot),var(--amber-soft));
    --gutter:168px;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html{height:100%; font-size:clamp(15px, 1.02vw, 19px)}
  body{height:100%; background:var(--bg); color:var(--ink); font-family:var(--sans);
    overflow:hidden; -webkit-font-smoothing:antialiased; line-height:1.5;}
  #deck{position:fixed; inset:0}
  .slide{position:absolute; inset:0; display:flex; flex-direction:column; justify-content:center;
    padding:4.5vh 4vw 5vh; opacity:0; visibility:hidden; transform:translateY(14px) scale(.995);
    transition:opacity .5s ease, transform .5s cubic-bezier(.2,.7,.2,1); pointer-events:none; overflow:hidden;}
  .slide.active{opacity:1; visibility:visible; transform:none; pointer-events:auto}
  .slide::before{content:""; position:absolute; inset:0; z-index:-2;
    background:radial-gradient(1200px 700px at 78% -10%, rgba(255,120,40,.10), transparent 60%),
      radial-gradient(900px 600px at 8% 110%, rgba(63,224,200,.06), transparent 55%), var(--bg);}
  .slide::after{content:""; position:absolute; inset:0; z-index:-1; opacity:.5;
    background-image:linear-gradient(rgba(255,255,255,.022) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255,255,255,.022) 1px, transparent 1px); background-size:46px 46px;
    -webkit-mask-image:radial-gradient(120% 100% at 50% 40%, #000 55%, transparent 100%);
            mask-image:radial-gradient(120% 100% at 50% 40%, #000 55%, transparent 100%);}
  .r{opacity:0; transform:translateY(16px); transition:opacity .6s ease, transform .6s cubic-bezier(.2,.7,.2,1)}
  .active .r{opacity:1; transform:none; transition-delay:calc(var(--d,0) * 1ms)}
  .max{max-width:1720px; margin:0 auto; width:100%}
  .kicker{font-family:var(--mono); font-size:.82rem; letter-spacing:.3em; text-transform:uppercase;
    color:var(--amber); display:inline-flex; align-items:center; gap:.6em; margin-bottom:1rem;}
  .kicker .dot{width:7px;height:7px;border-radius:50%;background:var(--amber);box-shadow:0 0 12px var(--amber-hot)}
  h1{font-size:clamp(2.6rem,6.4vw,6rem); font-weight:800; letter-spacing:-.02em; line-height:1.02}
  h2{font-size:clamp(1.5rem,3.2vw,2.7rem); font-weight:750; letter-spacing:-.015em; line-height:1.08; margin-bottom:.3rem}
  .lead{font-size:clamp(1rem,1.6vw,1.35rem); color:var(--mut); max-width:74ch; line-height:1.5}
  .em{color:var(--ink)} .am{color:var(--amber)} .cy{color:var(--cyan)} .gr{color:var(--green)} .rd{color:var(--red)} .vi{color:var(--violet)}
  b,strong{font-weight:700;color:var(--ink)}
  .tiny{font-size:.72rem;color:var(--mut2)}
  .title-wrap{position:relative}
  .ember{position:absolute; border-radius:50%; background:var(--amber); filter:blur(1px); opacity:0; animation:rise 6s ease-in infinite}
  @keyframes rise{0%{opacity:0;transform:translateY(40px) scale(.6)}20%{opacity:.8}100%{opacity:0;transform:translateY(-220px) scale(1.1)}}
  .statrow{display:flex; gap:2.6rem; flex-wrap:wrap; margin-top:2.4rem}
  .stat .sv{font-size:clamp(1.8rem,3.4vw,2.8rem); font-weight:800; color:var(--amber); line-height:1; font-family:var(--mono)}
  .stat .sl{font-size:.82rem; color:var(--mut); margin-top:.4rem; max-width:16ch}

  /* ---------- RAIL ---------- */
  .railslide{padding:3.4vh 3vw 3vh}
  .railwrap{display:flex; flex-direction:column; height:100%; justify-content:center; gap:.7rem}
  .railhead h2{font-size:clamp(1.2rem,2.2vw,1.9rem)}
  .legend{display:flex; gap:.5rem; flex-wrap:wrap; margin-top:.7rem}
  .chip{font-family:var(--mono); font-size:.72rem; display:inline-flex; align-items:center; gap:.5em;
    padding:.32em .7em; border-radius:8px; border:1px solid var(--line2); color:var(--mut);
    background:var(--panel); cursor:pointer; transition:.18s}
  .chip:hover{border-color:var(--amber); color:var(--ink)}
  .chip.on{border-color:var(--amber); color:var(--ink); box-shadow:0 0 0 1px var(--amber)}
  .chip.clear{color:var(--mut2)}
  .chip .sw, .lanelabel .sw{width:10px;height:10px;border-radius:50%;flex:none}
  .chip .lc, .lanelabel .lc{color:var(--mut2); font-size:.66rem}

  .eras{position:relative; height:34px; margin-left:var(--gutter); margin-bottom:.2rem}
  .eseg{position:absolute; top:0; bottom:0; border-left:1px solid var(--line2); border-radius:5px;
    padding:.25rem .5rem; overflow:hidden; display:flex; flex-direction:column; justify-content:center}
  .eseg .en{font-size:.72rem; font-weight:700; color:var(--ink); white-space:nowrap}
  .eseg .es{font-family:var(--mono); font-size:.6rem; color:var(--mut2); letter-spacing:.06em}

  .railplot{position:relative; border:1px solid var(--line); border-radius:14px;
    background:linear-gradient(180deg,var(--panel),var(--bg2)); padding:.4rem 0}
  .overlay{position:absolute; left:var(--gutter); right:0; top:0; bottom:26px; pointer-events:none; z-index:0}
  .eband{position:absolute; top:0; bottom:0; background:rgba(255,138,61,.045);
    border-left:1px dashed rgba(255,138,61,.35); border-right:1px dashed rgba(255,138,61,.35)}
  .eband .ebl{position:absolute; top:3px; left:50%; transform:translateX(-50%); font-family:var(--mono);
    font-size:.56rem; letter-spacing:.12em; color:var(--amber-soft); white-space:nowrap; opacity:.9}
  .tick{position:absolute; top:0; bottom:0; width:0; border-left:1px solid rgba(255,255,255,.04)}
  .tick span{position:absolute; bottom:-22px; left:0; transform:translateX(-50%); font-family:var(--mono);
    font-size:.6rem; color:var(--mut2); white-space:nowrap}
  .lanes{position:relative; z-index:1}
  .lane{display:grid; grid-template-columns:var(--gutter) 1fr; align-items:center; height:62px}
  .lane+.lane{border-top:1px solid rgba(255,255,255,.04)}
  .lanelabel{display:flex; align-items:center; gap:.5em; padding-left:1rem; font-size:.78rem; color:var(--mut)}
  .lanetrack{position:relative; height:100%}
  .node{position:absolute; top:calc(50% + var(--off,0px)); transform:translate(-50%,-50%);
    width:11px; height:11px; border-radius:50%; border:1px solid rgba(0,0,0,.35); padding:0;
    background:var(--mut); cursor:pointer; transition:.15s; display:block}
  .node[data-sub=scheduler]{background:var(--cyan)} .node[data-sub=pipeline]{background:var(--amber)}
  .node[data-sub=gates]{background:var(--green)} .node[data-sub=sdd]{background:var(--red)}
  .node[data-sub=obs]{background:var(--amber-soft)} .node[data-sub=infra]{background:var(--violet)}
  .node.hardening{width:8px;height:8px;opacity:.72}
  .node.foundational, .node.marquee{width:15px;height:15px;box-shadow:0 0 0 3px rgba(255,255,255,.08), 0 0 14px -2px currentColor}
  .node.marquee{box-shadow:0 0 0 3px rgba(255,138,61,.18), 0 0 16px -1px currentColor}
  .node:hover, .node:focus{transform:translate(-50%,-50%) scale(1.5); z-index:6; outline:none}
  /* inline labels (optional, toggled) */
  .node>.nlabel{position:absolute; left:12px; top:50%; transform:translateY(-50%); font-family:var(--mono);
    font-size:.55rem; line-height:1; white-space:nowrap; color:var(--mut); pointer-events:none; display:none;
    text-shadow:0 1px 2px #000, 0 0 3px #000, 0 0 3px #000; letter-spacing:.01em}
  .node:hover>.nlabel, .node:focus>.nlabel{color:var(--ink)}
  .railplot.lbl-key .node.marquee>.nlabel{display:block}
  .railplot.lbl-all .node>.nlabel{display:block}
  .railplot.lbl-all .node.hardening>.nlabel{color:var(--mut2)}
  .railplot.filtered .node{opacity:.12; filter:grayscale(.6)}
  .railplot.filtered .node.show{opacity:1; filter:none}
  .railplot.filtered .lane:not(.show) .lanelabel{opacity:.4}
  .axis{position:relative; height:18px; margin-left:var(--gutter); margin-top:2px}
  .axis .tick span{bottom:auto; top:0}
  .raillegend{margin-top:1.4rem; text-align:center}
  .raillegend .am{color:var(--amber-soft)}

  .tip{position:fixed; z-index:60; pointer-events:none; opacity:0; transform:translateY(4px);
    transition:opacity .12s ease; max-width:320px; background:#0c0e13; border:1px solid var(--line2);
    border-radius:10px; padding:.6rem .8rem; box-shadow:0 18px 40px -18px #000}
  .tip.on{opacity:1; transform:none}
  .tip .tt{font-weight:700; color:var(--ink); font-size:.9rem}
  .tip .tm{font-family:var(--mono); font-size:.64rem; color:var(--amber); letter-spacing:.06em; margin:.15rem 0 .35rem}
  .tip p{font-size:.78rem; color:var(--mut); line-height:1.45}

  /* ---------- scars ---------- */
  .scargrid{display:grid; grid-template-columns:repeat(5,1fr); gap:.8rem}
  .scard{background:linear-gradient(180deg,var(--panel),var(--bg2)); border:1px solid var(--line);
    border-left:2px solid var(--red); border-radius:12px; padding:.8rem .9rem}
  .scard .sh{display:flex; justify-content:space-between; align-items:baseline; gap:.4rem; margin-bottom:.35rem}
  .scard .sd{font-family:var(--mono); font-size:.62rem; color:var(--mut2)}
  .scard .sr{font-family:var(--mono); font-size:.62rem; color:var(--red)}
  .scard .st{font-weight:700; font-size:.84rem; line-height:1.2; margin-bottom:.3rem}
  .scard p{font-size:.74rem; color:var(--mut); line-height:1.4}

  /* ---------- in-flight ---------- */
  .flygrid{display:grid; grid-template-columns:repeat(5,1fr); gap:1rem}
  .fcard{display:block; text-decoration:none; background:linear-gradient(180deg,var(--panel),var(--bg2));
    border:1px solid var(--line); border-top:2px solid var(--ac); border-radius:13px; padding:1rem 1.1rem; transition:.18s}
  .fcard:hover{transform:translateY(-4px); border-color:var(--ac); box-shadow:0 18px 34px -22px var(--ac)}
  .fcard .fr{font-family:var(--mono); font-size:.7rem; color:var(--ac)}
  .fcard .ft{font-weight:700; font-size:.95rem; margin:.4rem 0 .4rem; color:var(--ink)}
  .fcard p{font-size:.8rem; color:var(--mut); line-height:1.45}

  /* ---------- epics ---------- */
  .epics{display:flex; flex-direction:column; gap:.7rem; margin-top:1rem}
  .eprow{display:grid; grid-template-columns:auto auto 1fr; align-items:center; gap:.9rem;
    background:linear-gradient(180deg,var(--panel),var(--bg2)); border:1px solid var(--line);
    border-left:3px solid var(--amber); border-radius:12px; padding:.8rem 1.1rem}
  .eprow .epref{font-family:var(--mono); font-weight:700; color:var(--amber); font-size:1rem}
  .eprow .epname{font-weight:700; font-size:1.05rem}
  .eprow .epclosed{font-family:var(--mono); font-size:.66rem; color:var(--mut2); justify-self:end}
  .eprow p{grid-column:1/-1; color:var(--mut); font-size:.86rem; margin-top:-.2rem}

  /* ---------- hud / chrome ---------- */
  .wm{position:fixed; top:2.4vh; left:3vw; z-index:30; font-family:var(--mono); font-size:.7rem;
    letter-spacing:.26em; text-transform:uppercase; color:var(--mut); display:flex; align-items:center; gap:.6em}
  .wm .b{width:14px;height:14px;border-radius:4px;background:var(--grad);box-shadow:0 0 14px rgba(255,106,26,.6)}
  #seclabel{position:fixed; top:2.4vh; right:3vw; z-index:30; font-family:var(--mono); font-size:.7rem;
    letter-spacing:.2em; text-transform:uppercase; color:var(--mut2)}
  #progress{position:fixed; left:0; bottom:0; height:3px; width:100%; background:rgba(255,255,255,.06); z-index:40}
  #bar{height:100%; width:0; background:var(--grad); box-shadow:0 0 14px rgba(255,106,26,.7); transition:width .5s ease}
  #hud{position:fixed; bottom:2.2vh; right:3vw; z-index:30; font-family:var(--mono); font-size:.72rem; color:var(--mut2)}
  #hud b{color:var(--amber)}
  .hint{position:fixed; bottom:2.2vh; left:3vw; z-index:30; font-family:var(--mono); font-size:.64rem; color:var(--mut2)}
  .hint span{color:var(--mut)}
  .navbtn{position:fixed; top:50%; transform:translateY(-50%); z-index:30; width:40px;height:40px; border-radius:50%;
    border:1px solid var(--line2); background:rgba(20,22,29,.6); color:var(--mut); cursor:pointer; font-size:1.1rem;
    display:grid; place-items:center; backdrop-filter:blur(6px); transition:.2s}
  .navbtn:hover{color:var(--ink); border-color:var(--amber)}
  #prev{left:1.4vw} #next{right:1.4vw}
  #overview{position:fixed; inset:0; z-index:50; background:rgba(7,8,11,.96); backdrop-filter:blur(8px);
    display:none; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:1rem; padding:8vh 6vw; overflow:auto; align-content:start}
  #overview.open{display:grid}
  .ov-card{border:1px solid var(--line); border-radius:12px; padding:1rem 1.1rem; cursor:pointer; background:var(--panel); transition:.2s; min-height:90px}
  .ov-card:hover{border-color:var(--amber); transform:translateY(-3px)}
  .ov-card .n{font-family:var(--mono); color:var(--amber); font-size:.74rem; letter-spacing:.1em}
  .ov-card .t{font-weight:650; margin-top:.4rem; font-size:.98rem; line-height:1.25}
  .ov-card .s{color:var(--mut2); font-size:.72rem; margin-top:.35rem; font-family:var(--mono); letter-spacing:.06em; text-transform:uppercase}
  #overview h2{grid-column:1/-1; margin-bottom:.4rem}
  #notes{position:fixed; left:0; right:0; bottom:0; z-index:45; transform:translateY(101%); transition:transform .35s ease;
    background:linear-gradient(180deg,#0d0f15,#090a0d); border-top:1px solid var(--amber); padding:1.3rem 6vw 2rem; max-height:42vh; overflow:auto}
  #notes.open{transform:none}
  #notes .lab{font-family:var(--mono); font-size:.66rem; letter-spacing:.22em; text-transform:uppercase; color:var(--amber); margin-bottom:.5rem}
  #notes p{color:var(--mut); font-size:.94rem; max-width:90ch}
  @media (max-width:1100px){ .scargrid,.flygrid{grid-template-columns:repeat(2,1fr)} .statrow{gap:1.4rem} :root{--gutter:120px} }
</style>
"""

JS = r"""
  const slides = Array.prototype.slice.call(document.querySelectorAll('.slide'));
  const total = slides.length; let cur = 0;
  const bar = document.getElementById('bar'), curEl = document.getElementById('cur'),
        totEl = document.getElementById('tot'), secEl = document.getElementById('seclabel'),
        ov = document.getElementById('overview'), notes = document.getElementById('notes'),
        noteText = document.getElementById('notetext');
  totEl.textContent = String(total).padStart(2,'0');
  function render(){
    slides.forEach((s,i)=>s.classList.toggle('active', i===cur));
    bar.style.width = ((cur+1)/total*100)+'%';
    curEl.textContent = String(cur+1).padStart(2,'0');
    secEl.textContent = slides[cur].getAttribute('data-sec') || '';
    noteText.textContent = NOTES[cur] || '';
  }
  function go(n){ cur = Math.max(0, Math.min(total-1, n)); render(); }
  function next(){ go(cur+1); } function prev(){ go(cur-1); }
  document.addEventListener('keydown', function(e){
    if(e.key==='ArrowRight'||e.key==='PageDown'||e.key===' '){ e.preventDefault(); if(!ov.classList.contains('open')) next(); }
    else if(e.key==='ArrowLeft'||e.key==='PageUp'){ e.preventDefault(); if(!ov.classList.contains('open')) prev(); }
    else if(e.key==='Home'){ go(0); } else if(e.key==='End'){ go(total-1); }
    else if(e.key==='o'||e.key==='O'){ toggleOv(); }
    else if(e.key==='n'||e.key==='N'){ notes.classList.toggle('open'); }
    else if(e.key==='f'||e.key==='F'){ toggleFs(); }
    else if(e.key==='Escape'){ if(ov.classList.contains('open')) toggleOv(); else notes.classList.remove('open'); }
  });
  document.getElementById('next').addEventListener('click', function(e){ e.stopPropagation(); next(); });
  document.getElementById('prev').addEventListener('click', function(e){ e.stopPropagation(); prev(); });
  document.getElementById('deck').addEventListener('click', function(e){
    if(ov.classList.contains('open')) return;
    if(e.target.closest('a,button,table,#notes,.tip,.railplot,.legend')) return;
    next();
  });
  function toggleFs(){ if(!document.fullscreenElement){ (document.documentElement.requestFullscreen||function(){})(); } else if(document.exitFullscreen){ document.exitFullscreen(); } }
  function buildOv(){
    ov.innerHTML = '<h2>Overview</h2>';
    slides.forEach(function(s,i){
      const sec = s.getAttribute('data-sec')||''; const h = s.querySelector('h1,h2');
      const title = i===0 ? 'The Dark Factory — Timeline' : (h?h.textContent.trim():'Slide '+(i+1));
      const c = document.createElement('div'); c.className='ov-card';
      c.innerHTML = '<div class="n">'+String(i+1).padStart(2,'0')+'</div><div class="t">'+title+'</div><div class="s">'+(sec||'Title')+'</div>';
      c.addEventListener('click', function(){ go(i); toggleOv(); }); ov.appendChild(c);
    });
  }
  let ovBuilt=false;
  function toggleOv(){ if(!ovBuilt){ buildOv(); ovBuilt=true; } ov.classList.toggle('open'); }

  // ---- rail: legend filter + tooltip ----
  const plot = document.getElementById('plot');
  if(plot){
    const tip = document.getElementById('tip');
    const chips = Array.prototype.slice.call(document.querySelectorAll('.chip'));
    let active = '';
    function applyFilter(sub){
      active = sub;
      plot.classList.toggle('filtered', !!sub);
      plot.querySelectorAll('.node').forEach(function(n){ n.classList.toggle('show', !!sub && n.getAttribute('data-sub')===sub); });
      plot.querySelectorAll('.lane').forEach(function(l){ l.classList.toggle('show', !!sub && l.getAttribute('data-sub')===sub); });
      chips.forEach(function(c){ if(c.id==='lblbtn') return; c.classList.toggle('on', !!sub && c.getAttribute('data-sub')===sub); });
    }
    chips.forEach(function(c){ if(c.id==='lblbtn') return; c.addEventListener('click', function(e){
      e.stopPropagation(); const sub = c.getAttribute('data-sub');
      applyFilter(active===sub ? '' : sub);
    }); });
    // inline-label toggle: off -> key (marquee only) -> all
    const lblbtn = document.getElementById('lblbtn');
    const lblStates = ['off','key','all'], lblText = {off:'Labels: off', key:'Labels: key', all:'Labels: all'};
    let lblIdx = 0;
    if(lblbtn){ lblbtn.addEventListener('click', function(e){
      e.stopPropagation(); lblIdx = (lblIdx+1)%3; const st = lblStates[lblIdx];
      plot.classList.remove('lbl-key','lbl-all');
      if(st!=='off') plot.classList.add('lbl-'+st);
      lblbtn.textContent = lblText[st]; lblbtn.classList.toggle('on', st!=='off');
    }); }
    function showTip(n){
      tip.innerHTML = '<div class="tt">'+n.getAttribute('data-title')+'</div>'+
        '<div class="tm">'+n.getAttribute('data-date')+(n.getAttribute('data-ref')?' · '+n.getAttribute('data-ref'):'')+'</div>'+
        '<p>'+n.getAttribute('data-desc')+'</p>';
      const r = n.getBoundingClientRect(); tip.classList.add('on');
      const tw = tip.offsetWidth, th = tip.offsetHeight;
      let left = r.left + r.width/2 - tw/2; left = Math.max(8, Math.min(window.innerWidth-tw-8, left));
      let top = r.top - th - 10; if(top < 8){ top = r.bottom + 10; }
      tip.style.left = left+'px'; tip.style.top = top+'px';
    }
    plot.querySelectorAll('.node').forEach(function(n){
      n.addEventListener('mouseenter', function(){ showTip(n); });
      n.addEventListener('focus', function(){ showTip(n); });
      n.addEventListener('mouseleave', function(){ tip.classList.remove('on'); });
      n.addEventListener('blur', function(){ tip.classList.remove('on'); });
    });
  }
  render();
"""

if __name__ == "__main__":
    main()
