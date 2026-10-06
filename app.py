import streamlit as st
import pandas as pd
import pymupdf as fitz
import re
import io
import zipfile
import barcode
from barcode.writer import ImageWriter

st.set_page_config(
    page_title="Amazon Invoice Barcode & Tracking Stamper",
    page_icon="📦",
    layout="centered"
)

st.title("📦 Amazon Invoice Barcode & Tracking Stamper")
st.write("Shipment Report aur multiple Invoice PDFs upload karein. **Strict PAN (AALCR5906L) + Exact SKU-to-Tracking Matching** apply hoga.")

TARGET_PAN = "aalcr5906l"

# File Uploaders
uploaded_csv = st.file_uploader("1. Upload Shipment Report (CSV / Excel)", type=["csv", "xlsx", "xls"])
uploaded_pdfs = st.file_uploader(
    "2. Upload Invoice PDF(s) - Ek sath multiple files select karein",
    type=["pdf"],
    accept_multiple_files=True
)

def clean_val(v):
    if pd.isna(v):
        return ""
    s = str(v).strip()
    s = re.sub(r'^[="\']+|["\']+$', '', s)
    return s.strip()

def clean_alphanumeric(text):
    """Normalize text: removes hyphens, spaces, special chars for 100% exact equality check"""
    return re.sub(r'[^a-zA-Z0-9]', '', str(text)).lower()

def extract_exact_sku_from_page(text):
    """
    Amazon invoice format: ASIN ( SKU )
    Example: B0DZ5WBCZD ( ORDMUPL80 ) -> extracts 'ordmupl80'
             B07H4QVBV8 ( ORDPM60 )   -> extracts 'ordpm60'
    """
    matches = re.findall(r'\(\s*([A-Za-z0-9_\-\.\/\s]+?)\s*\)', text)
    extracted = []
    for m in matches:
        cleaned = clean_alphanumeric(m)
        if len(cleaned) >= 3:
            extracted.append(cleaned)
    return extracted

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
    except Exception as e:
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
        st.error(f"File read error: {e}")
        st.stop()

    col_mapping = {str(col).strip().lower(): col for col in df.columns}
    order_col = next((col_mapping[c] for c in col_mapping if "order" in c), None)
    msku_col = next((col_mapping[c] for c in col_mapping if "sku" in c or "msku" in c), None)
    tracking_col = next((col_mapping[c] for c in col_mapping if "track" in c or "tracing" in c), None)

    st.success(f"Matched Columns: Order = **{order_col}** | SKU = **{msku_col}** | Tracking = **{tracking_col}**")

    if not (order_col and msku_col and tracking_col):
        st.error("CSV me required columns nahi mile!")
        st.stop()

    # Pre-build lookup map: (order_clean, sku_clean) -> tracking_id
    shipment_lookup = {}
    order_records_map = {}

    for _, row in df[[order_col, msku_col, tracking_col]].dropna().iterrows():
        raw_oid = clean_val(row[order_col])
        clean_oid = clean_alphanumeric(raw_oid)
        sku_val = clean_val(row[msku_col])
        sku_clean = clean_alphanumeric(sku_val)
        track_val = clean_val(row[tracking_col])

        if clean_oid and track_val:
            key = (clean_oid, sku_clean)
            shipment_lookup[key] = track_val

            if clean_oid not in order_records_map:
                order_records_map[clean_oid] = []
            order_records_map[clean_oid].append({
                "sku_val": sku_val,
                "sku_clean": sku_clean,
                "track": track_val
            })

    st.info(f"Total Unique Order Mappings: **{len(shipment_lookup)}** | Selected PDFs: **{len(uploaded_pdfs)} file(s)**")

    if st.button("🚀 Process Invoices (Exact SKU Match)", type="primary"):
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

                # Rule 1: Strict PAN check (AALCR5906L)
                if TARGET_PAN not in text_lower:
                    file_removed_pan += 1
                    continue

                # Order ID extraction
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
                        # Order has only 1 SKU in CSV
                        target_tracking_id = matching_rows[0]["track"]
                    else:
                        # Multi-SKU Order: Extract SKUs enclosed in brackets from this specific page
                        extracted_skus = extract_exact_sku_from_page(raw_text)

                        # Step 1: Direct Exact Key Match: (order, sku)
                        for cand_sku in extracted_skus:
                            if (order_clean, cand_sku) in shipment_lookup:
                                target_tracking_id = shipment_lookup[(order_clean, cand_sku)]
                                break

                        # Step 2: In case brackets had prefix/suffix, check substring equality
                        if not target_tracking_id:
                            for r in matching_rows:
                                if any(r["sku_clean"] == cand or cand in r["sku_clean"] or r["sku_clean"] in cand for cand in extracted_skus):
                                    target_tracking_id = r["track"]
                                    break

                        # Step 3: Raw page text match for exact SKU
                        if not target_tracking_id:
                            text_clean = clean_alphanumeric(raw_text)
                            for r in matching_rows:
                                if r["sku_clean"] and r["sku_clean"] in text_clean:
                                    target_tracking_id = r["track"]
                                    break

                # Rule 2: Stamping
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

            out_filename = f"Stamped_{pdf_file.name}"
            processed_files.append({
                "original_name": pdf_file.name,
                "file_name": out_filename,
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
                label="📦 Download All Files as ZIP",
                data=zip_buffer,
                file_name="All_Stamped_Invoices.zip",
                mime="application/zip",
                type="primary"
            )
            st.write("---")

        st.subheader("📄 Download Individual Files:")
        for idx, item in enumerate(processed_files):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"**{item['original_name']}** — ({item['pages']} pages kept, {item['stamped']} stamped, {item['removed']} non-PAN removed)")
            with col2:
                st.download_button(
                    label=f"📥 Download PDF",
                    data=item["data"],
                    file_name=item["file_name"],
                    mime="application/pdf",
                    key=f"dl_btn_{idx}"
                )
