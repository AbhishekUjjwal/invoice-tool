import streamlit as st
import pandas as pd
import pymupdf as fitz
import re
import io
import zipfile
import barcode
from barcode.writer import ImageWriter

# Page Configuration - Enterprise Wide Layout
st.set_page_config(
    page_title="Delhi Operations Hub | E-Commerce Automation",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
    <style>
    .main { background-color: #0f172a; color: #f8fafc; }
    .stMetric {
        background-color: #1e293b;
        padding: 12px;
        border-radius: 8px;
        border: 1px solid #334155;
    }
    .unit-card {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border: 1px solid #38bdf8;
        border-radius: 10px;
        padding: 12px;
        margin-bottom: 12px;
    }
    .unit-badge {
        background-color: #f59e0b;
        color: #000;
        font-weight: bold;
        font-size: 11px;
        padding: 2px 7px;
        border-radius: 4px;
        display: inline-block;
        margin-bottom: 6px;
    }
    </style>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.title("🏛️ Delhi Operations Hub")
    st.caption("Central E-Commerce Operations Portal")
    st.divider()

    st.markdown("**Active Unit Config:**")
    st.markdown("""
        <div class="unit-card">
            <span class="unit-badge">🏷️ AMZ-ED</span>
            <div style="font-weight: 600; font-size: 14px; color: #38bdf8;">Amazon Invoice Editor Unit</div>
            <div style="font-size: 12px; color: #cbd5e1; margin-top: 4px;">🎯 <b>Target PAN:</b> <code>AALCR5906L</code></div>
            <div style="font-size: 12px; color: #cbd5e1;">🏢 <b>Seller:</b> Romsons Prime Pvt Ltd</div>
        </div>
    """, unsafe_allow_html=True)

    st.divider()
    st.markdown("💡 **Supported Tools:**\n- 📑 Amazon Invoice Editor\n- ⚡ Blinkit e-Invoice Creator")

tab_amazon, tab_blinkit = st.tabs(["📑 Amazon Invoice Editor", "⚡ Blinkit e-Invoice Tool"])

# ----------------- TAB 1: AMAZON INVOICE EDITOR -----------------
with tab_amazon:
    st.subheader("📑 Amazon Invoice Editor (Product Description Matcher)")
    st.caption("Shipment Report aur Invoice PDF upload karein. Automatic PAN filter (AALCR5906L) + **Full Product Description Matching** apply hogi.")

    TARGET_PAN = "aalcr5906l"

    col_u1, col_u2 = st.columns(2)
    with col_u1:
        uploaded_csv = st.file_uploader("1. Upload Shipment Report (CSV / Excel)", type=["csv", "xlsx", "xls"], key="amz_csv")
    with col_u2:
        uploaded_pdfs = st.file_uploader("2. Upload Invoice PDF(s) [Multiple Files Allowed]", type=["pdf"], accept_multiple_files=True, key="amz_pdf")

    def clean_val(v):
        if pd.isna(v):
            return ""
        s = str(v).strip()
        s = re.sub(r'^[="\']+|["\']+$', '', s)
        return s.strip()

    def clean_alphanumeric(text):
        return re.sub(r'[^a-zA-Z0-9]', '', str(text)).lower()

    def get_token_words(text):
        """Extract meaningful words (length >= 2) for matching item descriptions"""
        words = re.findall(r'[a-zA-Z0-9]+', str(text).lower())
        stop_words = {'the', 'and', 'for', 'with', 'pcs', 'piece', 'pieces', 'only', 'total', 'hsn', 'gst', 'rs', 'inr'}
        return set([w for w in words if len(w) >= 2 and w not in stop_words])

    def generate_barcode_image(code_text):
        try:
            code128 = barcode.get_barcode_class('code128')
            writer = ImageWriter()
            writer.font_path = None
            barcode_instance = code128(code_text, writer=writer)
            
            buffer = io.BytesIO()
            barcode_instance.write(
                buffer,
                options={
                    'write_text': False,
                    'module_width': 0.45,
                    'module_height': 15.0,
                    'quiet_zone': 1.5,
                    'dpi': 300
                }
            )
            buffer.seek(0)
            return buffer.getvalue()
        except Exception:
            return None

    if uploaded_csv and uploaded_pdfs:
        try:
            if uploaded_csv.name.endswith(".csv"):
                try:
                    df = pd.read_csv(uploaded_csv, dtype=str)
                except UnicodeDecodeError:
                    uploaded_csv.seek(0)
                    df = pd.read_csv(uploaded_csv, encoding="latin1", dtype=str)
            else:
                df = pd.read_excel(uploaded_csv, dtype=str)
        except Exception as e:
            st.error(f"CSV read error: {e}")
            st.stop()

        col_mapping = {str(col).strip().lower(): col for col in df.columns}
        order_col = next((col_mapping[c] for c in col_mapping if "order" in c), None)
        tracking_col = next((col_mapping[c] for c in col_mapping if "track" in c or "tracing" in c), None)
        
        # Look for Title / Product / Description columns
        title_col = next((col_mapping[c] for c in col_mapping if any(k in c for k in ["title", "item-name", "item_name", "product", "desc"])), None)
        sku_col = next((col_mapping[c] for c in col_mapping if "sku" in c or "msku" in c), None)

        m1, m2, m3 = st.columns(3)
        m1.metric("Order Column", str(order_col))
        m2.metric("Product Description Column", str(title_col if title_col else sku_col))
        m3.metric("Tracking Column", str(tracking_col))

        if not (order_col and tracking_col):
            st.error("CSV me Order ID aur Tracking ID column hona zaroori hai!")
            st.stop()

        # Build order records
        order_records_map = {}
        for _, row in df.iterrows():
            raw_oid = clean_val(row.get(order_col, ""))
            clean_oid = clean_alphanumeric(raw_oid)
            track_val = clean_val(row.get(tracking_col, ""))

            # Build full searchable text from Title and SKU
            desc_parts = []
            if title_col and not pd.isna(row.get(title_col, "")):
                desc_parts.append(str(row[title_col]))
            if sku_col and not pd.isna(row.get(sku_col, "")):
                desc_parts.append(str(row[sku_col]))

            full_desc = " ".join(desc_parts).strip()
            desc_words = get_token_words(full_desc)

            if clean_oid and track_val:
                if clean_oid not in order_records_map:
                    order_records_map[clean_oid] = []
                order_records_map[clean_oid].append({
                    "full_desc": full_desc,
                    "desc_words": desc_words,
                    "track": track_val,
                    "used": False
                })

        st.info(f"📊 Unique Orders in CSV: **{len(order_records_map)}** | Selected PDFs: **{len(uploaded_pdfs)} file(s)**")

        if st.button("🚀 Process & Generate Stamped Invoices", type="primary", use_container_width=True):
            progress_bar = st.progress(0)
            status_text = st.empty()

            processed_files = []
            total_files = len(uploaded_pdfs)

            for file_idx, pdf_file in enumerate(uploaded_pdfs):
                status_text.text(f"Processing File {file_idx+1}/{total_files}: {pdf_file.name}...")

                pdf_bytes = pdf_file.read()
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                new_doc = fitz.open()

                total_pages = len(doc)
                file_stamped_count = 0
                file_removed_pan = 0

                for page_num in range(total_pages):
                    page = doc[page_num]
                    raw_text = page.get_text()
                    text_lower = raw_text.lower()

                    # Rule 1: Strict PAN Filter
                    if TARGET_PAN not in text_lower:
                        file_removed_pan += 1
                        continue

                    # Extract 17-digit Order Number
                    order_clean = None
                    order_match = re.search(r'(\d{3})\s*[-–—]\s*(\d{7})\s*[-–—]\s*(\d{7})', raw_text)
                    if order_match:
                        order_clean = f"{order_match.group(1)}{order_match.group(2)}{order_match.group(3)}"
                    else:
                        num_match = re.search(r'order\s*number\s*[:\s]*(\d{3}[-–—\d]{14,16}\d)', raw_text, re.IGNORECASE)
                        if num_match:
                            order_clean = clean_alphanumeric(num_match.group(1))

                    target_tracking_id = None

                    if order_clean and order_clean in order_records_map:
                        matching_rows = order_records_map[order_clean]

                        if len(matching_rows) == 1:
                            target_tracking_id = matching_rows[0]["track"]
                        else:
                            # MULTI-SKU ORDER: Match invoice description against CSV item descriptions
                            # Extract words specifically around Description area or whole page
                            page_words = get_token_words(raw_text)

                            best_match_row = None
                            highest_overlap = -1

                            for r in matching_rows:
                                if not r["desc_words"]:
                                    continue
                                # Intersection of common unique words (e.g. 'underpads', 'mattey', 'diapers')
                                common = page_words.intersection(r["desc_words"])
                                overlap_score = len(common)

                                if overlap_score > highest_overlap:
                                    highest_overlap = overlap_score
                                    best_match_row = r

                            if best_match_row and highest_overlap > 0:
                                target_tracking_id = best_match_row["track"]
                                best_match_row["used"] = True
                            else:
                                # Fallback: unused row if words couldn't match
                                unused_rows = [r for r in matching_rows if not r["used"]]
                                if unused_rows:
                                    target_tracking_id = unused_rows[0]["track"]
                                    unused_rows[0]["used"] = True
                                else:
                                    target_tracking_id = matching_rows[0]["track"]

                    # Stamping Barcode and Tracking ID
                    if target_tracking_id:
                        barcode_rect = fitz.Rect(40, 58, 235, 82)
                        page.draw_rect(barcode_rect, color=(1.0, 1.0, 1.0), fill=(1.0, 1.0, 1.0), width=0)

                        barcode_img_bytes = generate_barcode_image(target_tracking_id)
                        if barcode_img_bytes:
                            page.insert_image(barcode_rect, stream=barcode_img_bytes, keep_proportion=False)

                        page.insert_text(
                            (barcode_rect.x0 + 10, 95),
                            f"TRACKING: {target_tracking_id}",
                            fontsize=10.5,
                            fontname="hebo",
                            color=(0, 0, 0)
                        )

                        date_instances = page.search_for("Order Date:") or page.search_for("Order Date")
                        if date_instances:
                            first_date_rect = date_instances[0]
                            page.insert_text(
                                (first_date_rect.x0, first_date_rect.y1 + 13),
                                f"Tracking ID: {target_tracking_id}",
                                fontsize=9.5,
                                fontname="hebo",
                                color=(0, 0, 0)
                            )

                        file_stamped_count += 1

                    new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)

                out_buf = io.BytesIO()
                new_doc.save(out_buf)
                out_buf.seek(0)

                processed_files.append({
                    "original_name": pdf_file.name,
                    "file_name": f"Stamped_{pdf_file.name}",
                    "data": out_buf.getvalue(),
                    "pages": len(new_doc),
                    "stamped": file_stamped_count,
                    "removed": file_removed_pan
                })

                progress_bar.progress((file_idx + 1) / total_files)

            status_text.empty()
            progress_bar.empty()

            st.balloons()
            st.success(f"🎉 **Total {len(processed_files)} File(s) Processed Successfully!**")

            if len(processed_files) > 1:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                    for item in processed_files:
                        zip_file.writestr(item["file_name"], item["data"])
                zip_buffer.seek(0)

                st.download_button(
                    label="📦 Download All Invoices as ZIP",
                    data=zip_buffer,
                    file_name="All_Stamped_Invoices.zip",
                    mime="application/zip",
                    use_container_width=True
                )

            st.write("---")
            st.subheader("📄 Individual Download Files:")
            for idx, item in enumerate(processed_files):
                d_col1, d_col2 = st.columns([3, 1])
                with d_col1:
                    st.write(f"📁 **{item['original_name']}** — `{item['pages']} Pages Kept` | `{item['stamped']} Stamped` | `{item['removed']} Non-PAN Filtered`")
                with d_col2:
                    st.download_button(
                        label="📥 Download PDF",
                        data=item["data"],
                        file_name=item["file_name"],
                        mime="application/pdf",
                        key=f"dl_btn_{idx}",
                        use_container_width=True
                    )

# ----------------- TAB 2: BLINKIT TOOL -----------------
with tab_blinkit:
    st.subheader("⚡ Blinkit e-Invoice Management Tool")
    st.caption("Blinkit purchase orders, ASN aur e-invoicing automation portal.")
    st.info("Blinkit Tool ka script code share karein, use is tab me activate kar diya jayega.")
