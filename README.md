# Azure Durable Functions Image Analyzer

## Overview

This project is an Azure Durable Functions application that analyzes images uploaded to Azure Blob Storage. When an image is uploaded to the `images` container, the function performs multiple analyses including:

- Color analysis
- Object detection (mock)
- Text detection (mock)
- Metadata extraction

The results are stored in Azure Table Storage and can be retrieved using an HTTP endpoint.

---

## Prerequisites

Make sure the following tools are installed:

- Python 3.12
- Azure Functions Core Tools v4  
  https://learn.microsoft.com/azure/azure-functions/functions-run-local
- Azure CLI  
  https://learn.microsoft.com/cli/azure/install-azure-cli
- Visual Studio Code
- VS Code Azure Functions Extension
- Azurite (Azure Storage Emulator)

---

## Setup Instructions

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO
```

### 2. Create virtual environment

Mac/Linux:
```bash
python -m venv .venv
source .venv/bin/activate
```
Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
```
### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create local.settings.json

Create a file named:

```bash
local.settings.json
```

Example content:

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "ImageStorageConnection": "UseDevelopmentStorage=true"
  }
}
```

### 5. Start Azurite (Storage Emulator)

In VS Code:

Press:
```bash
Cmd + Shift + P
```
Then run:
```bash
Azurite: Start
```

### 6. Run the Function App locally
``
```bash
func start
```

You should see output showing all functions loaded.

### 7. Test the HTTP endpoint

Open in browser:
```bash
http://localhost:7071/api/results
```

### 8. Upload an image to trigger analysis

Upload an image to the images container using:

Azure Storage Explorer, or

Azurite Explorer, or

Azure Portal

The Blob Trigger will automatically start the analysis workflow.
```bash
GET /api/results
```

Returns:
```json
{
  "count": 1,
  "results": [
    {
      "id": "...",
      "fileName": "test.jpg",
      "analyzedAt": "...",
      "summary": {
        "imageSize": "770x400",
        "format": "JPEG",
        "dominantColor": "#000000",
        "objectsDetected": 2,
        "hasText": false,
        "isGrayscale": false
      }
    }
  ]
}
```


### Demo

[Video](https://youtu.be/Az7pxM3GoMc)
