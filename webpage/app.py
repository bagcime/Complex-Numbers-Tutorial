# app.py
from flask import Flask, render_template_string
import json
from data import DATA  # your big dictionary {index: "DEIDENTIFIED_TEXT", ...}
import os
from pathlib import Path

CSV_FILE_NOTES = Path(os.getenv("CSV_FILE_NOTES", "data/Asthma_Symp.csv"))
CSV_FILE_LABS  = Path(os.getenv("CSV_FILE_LABS",  "data/symptom_patient_merged.csv"))
app = Flask(__name__)

LABEL_COLS = [
    "wheezing_current", "wheezing_previous",
    "shortness_of_breath_current", "shortness_of_breath_previous",
    "chest_tightness_current", "chest_tightness_previous",
    "coughing_current", "coughing_previous",
    "rapid_breathing_current", "rapid_breathing_previous",
    "exercise_induced_symptoms_current", "exercise_induced_symptoms_previous",
    "nocturnal_symptoms_current", "nocturnal_symptoms_previous",
    "exacerbation_current", "exacerbation_previous",
    "general_asthma_symptoms_worsening_current"
]

TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Annotation UI (Offline SPA)</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root { --border:#ddd; --bg:#fafafa; --muted:#f6f6f6; --primary:#0d6efd; }
    body { font-family: Arial, sans-serif; margin: 14px; }
    .header { margin-bottom: 10px; }
    .container { display: flex; gap: 24px; }
    .left { flex: 0 0 58%; }
    .right { flex: 1; }
    .box {
      height: 420px; overflow-y: auto; padding: 12px;
      border: 1px solid var(--border); border-radius: 6px; background: var(--bg);
      white-space: pre-wrap; line-height: 1.35;
      font-family: 'Times New Roman', serif; font-size: 16px;
    }
    .label-group { margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px dashed #eee; }
    .label-title { font-weight: 600; display: block; margin-bottom: 4px; }
    .radio-inline { display: inline-block; margin-right: 16px; }
    .btn-row { display: flex; gap: 10px; margin-top: 12px; flex-wrap: wrap; }
    button {
      padding: 8px 14px; border: 1px solid #bbb; background: #fff;
      border-radius: 6px; cursor: pointer;
    }
    button.primary { background: var(--primary); color: white; border-color: var(--primary); }
    button:hover { opacity: 0.95; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 6px 8px; border: 1px solid #e5e5e5; font-size: 14px; }
    th { background: var(--muted); text-align: left; }
    .footer { margin-top: 22px; }
    .small { color:#666; font-size: 13px; }
  </style>
</head>
<body>
  <div class="header">
    <h2>Annotation Interface (Offline)</h2>
    <div><strong>Index:</strong> <span id="cur-index"></span>
      &nbsp; | &nbsp; <strong>Row:</strong> <span id="row-no"></span> / <span id="row-total"></span>
    </div>
    <div class="small">No page reloads. All actions handled in-browser.</div>
  </div>

  <div class="container">
    <div class="left">
      <h3>De-identified Text</h3>
      <div id="text-box" class="box"></div>
    </div>

    <div class="right">
      <h3>Labels</h3>
      <div id="labels"></div>

      <div class="btn-row">
        <button id="btn-print" class="primary">Print (Add Annotation)</button>
        <button id="btn-prev">⬅️ Previous Text</button>
        <button id="btn-next">Next Text ➡️</button>
      </div>
    </div>
  </div>

  <div class="footer">
    <h3>Annotated Results (Newest First)</h3>
    <div id="no-annotations">No annotations yet. Click <strong>Print</strong> to add the current selection.</div>
    <div style="overflow-x:auto; display:none;" id="table-wrap">
      <table id="ann-table">
        <thead>
          <tr>
            <th>index</th>
            {% for col in label_cols %}
              <th>{{ col }}</th>
            {% endfor %}
          </tr>
        </thead>
        <tbody id="ann-body"></tbody>
      </table>
    </div>
  </div>

  <script>
    // ==== Embedded data from Python ====
    const DATA = {{ data_json | safe }};
    const LABEL_COLS = {{ label_cols_json | safe }};
    const IDS = Object.keys(DATA).map(Number).sort((a,b)=>a-b);

    // ==== State ====
    let pos = 0; // pointer into IDS
    let annotations = []; // newest first
    // Optional: persist in localStorage
    try {
      const saved = localStorage.getItem("annotations");
      if (saved) annotations = JSON.parse(saved);
    } catch(e){}

    // ==== Helpers ====
    function pretty(lbl) {
      const s = lbl.replaceAll("_", " ");
      return s.charAt(0).toUpperCase() + s.slice(1);
    }

    function setText(text) {
      const box = document.getElementById("text-box");
      box.textContent = text; // safe display, preserves newlines via CSS
      box.scrollTop = 0;
    }

    function renderHeader() {
      document.getElementById("cur-index").textContent = IDS[pos];
      document.getElementById("row-no").textContent = (pos + 1);
      document.getElementById("row-total").textContent = IDS.length;
    }

    function buildRadios() {
      const wrap = document.getElementById("labels");
      wrap.innerHTML = "";
      LABEL_COLS.forEach(col => {
        const group = document.createElement("div");
        group.className = "label-group";
        const title = document.createElement("span");
        title.className = "label-title";
        title.textContent = pretty(col);

        const falseLbl = document.createElement("label");
        falseLbl.className = "radio-inline";
        const falseInp = document.createElement("input");
        falseInp.type = "radio"; falseInp.name = col; falseInp.value = "False"; falseInp.checked = true;
        falseLbl.appendChild(falseInp);
        falseLbl.appendChild(document.createTextNode(" False"));

        const trueLbl = document.createElement("label");
        trueLbl.className = "radio-inline";
        const trueInp = document.createElement("input");
        trueInp.type = "radio"; trueInp.name = col; trueInp.value = "True";
        trueLbl.appendChild(trueInp);
        trueLbl.appendChild(document.createTextNode(" True"));

        group.appendChild(title);
        group.appendChild(falseLbl);
        group.appendChild(trueLbl);
        wrap.appendChild(group);
      });
    }

    function resetRadios() {
      LABEL_COLS.forEach(col => {
        const inp = document.querySelector(`input[name="${col}"][value="False"]`);
        if (inp) inp.checked = true;
      });
    }

    function collectRadios() {
      const rec = { index: IDS[pos] };
      LABEL_COLS.forEach(col => {
        const val = document.querySelector(`input[name="${col}"]:checked`)?.value || "False";
        rec[col] = (val === "True");
      });
      return rec;
    }

    function renderAnnotationsTable() {
      const body = document.getElementById("ann-body");
      const wrap = document.getElementById("table-wrap");
      const empty = document.getElementById("no-annotations");

      if (annotations.length === 0) {
        wrap.style.display = "none";
        empty.style.display = "block";
        body.innerHTML = "";
        return;
      }
      empty.style.display = "none";
      wrap.style.display = "block";

      body.innerHTML = "";
      annotations.forEach(rec => {
        const tr = document.createElement("tr");
        const tdIdx = document.createElement("td");
        tdIdx.textContent = rec.index;
        tr.appendChild(tdIdx);

        LABEL_COLS.forEach(col => {
          const td = document.createElement("td");
          td.textContent = rec[col];
          tr.appendChild(td);
        });
        body.appendChild(tr);
      });
    }

    function saveAnnotations() {
      try { localStorage.setItem("annotations", JSON.stringify(annotations)); } catch(e){}
    }

    // ==== Navigation ====
    function goNext() {
      pos = (pos + 1) % IDS.length;
      renderHeader();
      setText(DATA[IDS[pos]]);
      resetRadios(); // requirement: reset on navigation
    }
    function goPrev() {
      pos = (pos - 1 + IDS.length) % IDS.length;
      renderHeader();
      setText(DATA[IDS[pos]]);
      resetRadios();
    }

    // ==== Events ====
    document.addEventListener("DOMContentLoaded", () => {
      // initial render
      renderHeader();
      setText(DATA[IDS[pos]]);
      buildRadios();
      renderAnnotationsTable();

      document.getElementById("btn-next").addEventListener("click", (e) => {
        e.preventDefault();
        goNext();
      });
      document.getElementById("btn-prev").addEventListener("click", (e) => {
        e.preventDefault();
        goPrev();
      });
      document.getElementById("btn-print").addEventListener("click", (e) => {
        e.preventDefault();
        const rec = collectRadios();
        annotations.unshift(rec); // newest first
        renderAnnotationsTable();
        saveAnnotations();
      });
    });
  </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(
        TEMPLATE,
        data_json=json.dumps(DATA, ensure_ascii=False),
        label_cols_json=json.dumps(LABEL_COLS),
        label_cols=LABEL_COLS
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

