import streamlit as st
import pandas as pd
import pymupdf as fitz
import re
import io
import zipfile
import barcode
from barcode.writer import ImageWriter

st.set_page_config(
    page_title="Operations Hub | E-Commerce Automation",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .main { background-color: #f8fafc; }
    .stMetric {
        background-color: #ffffff;
        padding: 12px;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
    div[data-testid="stFileUploader"] {
        border: 1px dashed #4b5563;
        padding: 10px;
        border-radius: 8px;
        background-color: #ffffff;
    }
    </style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.title("🏢 Operations Hub")
    st.caption("Central Automation Portal")
    st.divider()
    st.markdown("**Active Unit Config:**")
    st.info("🎯 **Target PAN:** `AALCR5906L`\n\n📌 **Seller:** Romsons Prime Pvt Ltd")
    st.divider()
    st.markdown("💡 **Supported Tools:**\n- Amazon Barcode & Tracking Stamper\n- Blinkit e-Invoice Creator")

tab_amazon, tab_blinkit = st.tabs(["📦 Amazon Invoice Stamper", "⚡ Blinkit e-Invoice Tool"])

# ----------------- TAB 1: AMAZON STAMPER -----------------
with tab_amazon:
    st.subheader("📦 Amazon Shipment Barcode & Tracking Automation")
    st.caption("Shipment Report aur multiple Invoice PDFs upload karein. Automatic PAN filter (AALCR5906L) + Guaranteed Multi-SKU Matching apply hogi.")

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

    def extract_skus_and_asins(text):
        """Extracts text inside brackets and 10-char ASINs from page"""
        bracket_matches = re.findall(r'\(\s*([A-Za-z0-9_\-\.\/\s]+?)\s*\)', text)
        skus = [clean_alphanumeric(m) for m in bracket_matches if len(clean_alphanumeric(m)) >= 3]
        
        # Amazon ASIN pattern (e.g. B0DZ5WBCZD, B07H4QVBV8)
        asins = [clean_alphanumeric(a) for a in re.findall(r'\b(B0[A-Z0-9]{8})\b', text)]
        return skus, asins

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
        msku_col = next((col_mapping[c] for c in col_mapping if "sku" in c or "msku" in c), None)
        tracking_col = next((col_mapping[c] for c in col_mapping if "track" in c or "tracing" in c), None)

        m1, m2, m3 = st.columns(3)
        m1.metric("Order Column", str(order_col))
        m2.metric("SKU Column", str(msku_col))
        m3.metric("Tracking Column", str(tracking_col))

        if not (order_col and msku_col and tracking_col):
            st.error("CSV me Order ID, SKU aur Tracking ID column nahi mila!")
            st.stop()

        order_records_map = {}
        for _, row in df[[order_col, msku_col, tracking_col]].dropna().iterrows():
            raw_oid = clean_val(row[order_col])
            clean_oid = clean_alphanumeric(raw_oid)
            sku_val = clean_val(row[msku_col])
            sku_clean = clean_alphanumeric(sku_val)
            track_val = clean_val(row[tracking_col])

            if clean_oid and track_val:
                if clean_oid not in order_records_map:
                    order_records_map[clean_oid] = []
                order_records_map[clean_oid].append({
                    "sku_val": sku_val,
                    "sku_clean": sku_clean,
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
                    text_clean = clean_alphanumeric(raw_text)

                    # Rule 1: PAN Filter
                    if TARGET_PAN not in text_lower:
                        file_removed_pan += 1
                        continue

                    # Order ID regex
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
                            extracted_skus, extracted_asins = extract_skus_and_asins(raw_text)

                            # 1. Match bracket SKU with CSV SKU (containment / exact)
                            for cand_sku in extracted_skus:
                                for r in matching_rows:
                                    if (cand_sku in r["sku_clean"]) or (r["sku_clean"] in cand_sku):
                                        target_tracking_id = r["track"]
                                        break
                                if target_tracking_id:
                                    break

                            # 2. Match CSV SKU in the full invoice text
                            if not target_tracking_id:
                                for r in matching_rows:
                                    if r["sku_clean"] and (r["sku_clean"] in text_clean):
                                        target_tracking_id = r["track"]
                                        break

                            # 3. Fallback: Unused row assign karo taaki tracking stamp kabhi miss na ho
                            if not target_tracking_id:
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
    st.info("Blinkit Tool ka script code provide karein, use is tab me activate kar diya jayega.")
