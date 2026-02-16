import azure.functions as func
import azure.durable_functions as df
from azure.data.tables import TableServiceClient
from azure.storage.blob import BlobServiceClient
from PIL import Image

import logging
import json
import io
import os
import uuid
from datetime import datetime

app = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)

TABLE_NAME = "ImageAnalysisResults"
PARTITION_KEY = "ImageAnalysis"


def get_table_client():
    connection_string = os.environ["ImageStorageConnection"]
    table_service = TableServiceClient.from_connection_string(connection_string)
    table_service.create_table_if_not_exists(TABLE_NAME)
    return table_service.get_table_client(TABLE_NAME)


def download_blob_bytes(blob_name: str) -> bytes:
    """
    blob_name looks like: 'images/file.jpg'
    """
    conn_str = os.environ["ImageStorageConnection"]
    service = BlobServiceClient.from_connection_string(conn_str)

    if "/" in blob_name:
        container, blob = blob_name.split("/", 1)
    else:
        container, blob = "images", blob_name

    blob_client = service.get_blob_client(container=container, blob=blob)
    return blob_client.download_blob().readall()


# 1) Blob trigger (client)
@app.blob_trigger(arg_name="myblob", path="images/{name}", connection="ImageStorageConnection")
@app.durable_client_input(client_name="client")
async def blob_trigger(myblob: func.InputStream, client):
    blob_name = myblob.name
    blob_size_kb = round(myblob.length / 1024, 2)

    logging.info(f"New image detected: {blob_name} ({blob_size_kb} KB)")

    instance_id = await client.start_new(
        "image_analyzer_orchestrator",
        client_input={"blob_name": blob_name, "blob_size_kb": blob_size_kb},
    )

    logging.info(f"Started orchestration {instance_id} for {blob_name}")


# 2) Orchestrator (fan-out / fan-in + chaining)
@app.orchestration_trigger(context_name="context")
def image_analyzer_orchestrator(context):
    input_data = context.get_input()

    analysis_tasks = [
        context.call_activity("analyze_colors", input_data),
        context.call_activity("analyze_objects", input_data),
        context.call_activity("analyze_text", input_data),
        context.call_activity("analyze_metadata", input_data),
    ]

    results = yield context.task_all(analysis_tasks)

    report_input = {
        "blob_name": input_data["blob_name"],
        "colors": results[0],
        "objects": results[1],
        "text": results[2],
        "metadata": results[3],
    }

    report = yield context.call_activity("generate_report", report_input)
    record = yield context.call_activity("store_results", report)
    return record


# 3) Analyze colors (real)
@app.activity_trigger(input_name="inputData")
def analyze_colors(inputData: dict):
    logging.info("Analyzing colors...")

    try:
        image_bytes = download_blob_bytes(inputData["blob_name"])
        image = Image.open(io.BytesIO(image_bytes))

        if image.mode != "RGB":
            image = image.convert("RGB")

        small_image = image.resize((50, 50))
        pixels = list(small_image.getdata())

        color_counts = {}
        for r, g, b in pixels:
            key = (r // 32 * 32, g // 32 * 32, b // 32 * 32)
            color_counts[key] = color_counts.get(key, 0) + 1

        sorted_colors = sorted(color_counts.items(), key=lambda x: x[1], reverse=True)

        top_colors = []
        for (r, g, b), count in sorted_colors[:5]:
            top_colors.append({
                "hex": f"#{r:02x}{g:02x}{b:02x}",
                "rgb": {"r": r, "g": g, "b": b},
                "percentage": round(count / len(pixels) * 100, 1),
            })

        grayscale_pixels = sum(
            1 for r, g, b in pixels if abs(r - g) < 30 and abs(g - b) < 30
        )
        is_grayscale = grayscale_pixels / len(pixels) > 0.9

        return {
            "dominantColors": top_colors,
            "isGrayscale": is_grayscale,
            "totalPixelsSampled": len(pixels),
        }

    except Exception as e:
        logging.exception("Color analysis failed")
        return {"dominantColors": [], "isGrayscale": False, "totalPixelsSampled": 0, "error": str(e)}


# 4) Analyze objects (mock)
@app.activity_trigger(input_name="inputData")
def analyze_objects(inputData: dict):
    logging.info("Analyzing objects...")

    try:
        image_bytes = download_blob_bytes(inputData["blob_name"])
        image = Image.open(io.BytesIO(image_bytes))
        width, height = image.size

        mock_objects = []
        if width > height:
            mock_objects.append({"name": "landscape", "confidence": 0.85})
        elif height > width:
            mock_objects.append({"name": "portrait", "confidence": 0.82})
        else:
            mock_objects.append({"name": "square composition", "confidence": 0.90})

        if width * height > 1_000_000:
            mock_objects.append({"name": "high-resolution scene", "confidence": 0.78})

        mock_objects.append({"name": "digital image", "confidence": 0.99})

        return {"objects": mock_objects, "objectCount": len(mock_objects), "note": "Mock analysis"}

    except Exception as e:
        logging.exception("Object analysis failed")
        return {"objects": [], "objectCount": 0, "error": str(e)}


# 5) Analyze text (mock)
@app.activity_trigger(input_name="inputData")
def analyze_text(inputData: dict):
    logging.info("Analyzing text (OCR)...")
    return {"hasText": False, "extractedText": "", "confidence": 0.0, "language": "unknown", "note": "Mock OCR"}


# 6) Analyze metadata (real)
@app.activity_trigger(input_name="inputData")
def analyze_metadata(inputData: dict):
    logging.info("Analyzing metadata...")

    try:
        image_bytes = download_blob_bytes(inputData["blob_name"])
        image = Image.open(io.BytesIO(image_bytes))

        width, height = image.size
        total_pixels = width * height

        return {
            "width": width,
            "height": height,
            "format": image.format or "Unknown",
            "mode": image.mode,
            "totalPixels": total_pixels,
            "megapixels": round(total_pixels / 1_000_000, 2),
            "sizeKB": inputData.get("blob_size_kb"),
        }

    except Exception as e:
        logging.exception("Metadata analysis failed")
        return {"width": 0, "height": 0, "format": "Unknown", "error": str(e)}


# 7) Generate report
@app.activity_trigger(input_name="reportData")
def generate_report(reportData: dict):
    logging.info("Generating combined report...")

    blob_name = reportData["blob_name"]
    filename = blob_name.split("/")[-1] if "/" in blob_name else blob_name

    report = {
        "id": str(uuid.uuid4()),
        "fileName": filename,
        "blobPath": blob_name,
        "analyzedAt": datetime.utcnow().isoformat(),
        "analyses": {
            "colors": reportData["colors"],
            "objects": reportData["objects"],
            "text": reportData["text"],
            "metadata": reportData["metadata"],
        },
        "summary": {
            "imageSize": f"{reportData['metadata'].get('width', 0)}x{reportData['metadata'].get('height', 0)}",
            "format": reportData["metadata"].get("format", "Unknown"),
            "dominantColor": reportData["colors"]["dominantColors"][0]["hex"]
            if reportData["colors"].get("dominantColors") else "N/A",
            "objectsDetected": reportData["objects"].get("objectCount", 0),
            "hasText": reportData["text"].get("hasText", False),
            "isGrayscale": reportData["colors"].get("isGrayscale", False),
        }
    }

    return report


# 8) Store results
@app.activity_trigger(input_name="report")
def store_results(report: dict):
    logging.info(f"Storing results for {report['fileName']}...")

    table_client = get_table_client()

    entity = {
        "PartitionKey": PARTITION_KEY,
        "RowKey": report["id"],
        "FileName": report["fileName"],
        "BlobPath": report["blobPath"],
        "AnalyzedAt": report["analyzedAt"],
        "Summary": json.dumps(report["summary"]),
        "ColorAnalysis": json.dumps(report["analyses"]["colors"]),
        "ObjectAnalysis": json.dumps(report["analyses"]["objects"]),
        "TextAnalysis": json.dumps(report["analyses"]["text"]),
        "MetadataAnalysis": json.dumps(report["analyses"]["metadata"]),
    }

    table_client.upsert_entity(entity)

    logging.info(f"Results stored with ID: {report['id']}")
    return {"id": report["id"], "fileName": report["fileName"], "status": "stored", "analyzedAt": report["analyzedAt"]}


# 9) HTTP get results
@app.route(route="results/{id?}")
def get_results(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Get results endpoint called")

    try:
        table_client = get_table_client()
        result_id = req.route_params.get("id")

        if result_id:
            entity = table_client.get_entity(PARTITION_KEY, result_id)
            result = {
                "id": entity["RowKey"],
                "fileName": entity["FileName"],
                "blobPath": entity["BlobPath"],
                "analyzedAt": entity["AnalyzedAt"],
                "summary": json.loads(entity["Summary"]),
                "analyses": {
                    "colors": json.loads(entity["ColorAnalysis"]),
                    "objects": json.loads(entity["ObjectAnalysis"]),
                    "text": json.loads(entity["TextAnalysis"]),
                    "metadata": json.loads(entity["MetadataAnalysis"]),
                },
            }
            return func.HttpResponse(json.dumps(result, indent=2), mimetype="application/json", status_code=200)

        limit = int(req.params.get("limit", "10"))
        entities = list(table_client.query_entities(f"PartitionKey eq '{PARTITION_KEY}'"))

        results = [{
            "id": e["RowKey"],
            "fileName": e["FileName"],
            "analyzedAt": e["AnalyzedAt"],
            "summary": json.loads(e["Summary"]),
        } for e in entities]

        results.sort(key=lambda x: x["analyzedAt"], reverse=True)
        results = results[:limit]

        return func.HttpResponse(
            json.dumps({"count": len(results), "results": results}, indent=2),
            mimetype="application/json",
            status_code=200,
        )

    except Exception as e:
        logging.exception("Failed to retrieve results")
        return func.HttpResponse(json.dumps({"error": str(e)}), mimetype="application/json", status_code=500)
