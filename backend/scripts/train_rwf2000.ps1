# Download (resume), verify, extract and train the VIAHIND fight classifier on RWF-2000, on the GPU.
# Runs in its own window, independent of Claude Code. Progress is also written to C:\Users\v\datasets\training.log
#
#   powershell -ExecutionPolicy Bypass -File backend\scripts\train_rwf2000.ps1
#
# Licence note: this uses a third-party Hugging Face copy of RWF-2000. Confirm the original authors'
# terms before any commercial use of the resulting model.

$ErrorActionPreference = "Stop"
$Datasets = "C:\Users\v\datasets"
$Archive = Join-Path $Datasets "RWF-2000.tar.gz"
$Extract = Join-Path $Datasets "RWF-2000-data"
$Log = Join-Path $Datasets "training.log"
$Backend = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Backend ".venv\Scripts\python.exe"
$Url = "https://huggingface.co/datasets/DanJoshua/RWF-2000/resolve/main/RWF-2000.tar.gz"
$ExpectedBytes = 12315601005

New-Item -ItemType Directory -Force $Datasets | Out-Null
Start-Transcript -Path $Log -Append | Out-Null
try {
    Write-Host "== 1/4 Download (resumes a partial file) =="
    for ($i = 1; $i -le 20; $i++) {
        $have = if (Test-Path $Archive) { (Get-Item $Archive).Length } else { 0 }
        if ($have -ge $ExpectedBytes) { break }
        Write-Host ("Attempt {0}: have {1:N2} GB of {2:N2} GB" -f $i, ($have / 1GB), ($ExpectedBytes / 1GB))
        & curl.exe -L --fail --retry 10 --retry-delay 5 -C - -o $Archive $Url
        Start-Sleep -Seconds 3
    }
    if ((Get-Item $Archive).Length -lt $ExpectedBytes) { throw "Download incomplete after 20 attempts. Run this script again to resume." }

    Write-Host "== 2/4 Extract =="
    if (-not (Test-Path (Join-Path $Extract ".extracted"))) {
        if (Test-Path $Extract) { Remove-Item -Recurse -Force $Extract }
        New-Item -ItemType Directory -Force $Extract | Out-Null
        & tar.exe -xzf $Archive -C $Extract
        if ($LASTEXITCODE -ne 0) { throw "Extraction failed (the archive may be corrupt). Delete $Archive and run again." }
        New-Item -ItemType File (Join-Path $Extract ".extracted") | Out-Null
    }
    $videos = Get-ChildItem -Recurse -File $Extract -Include *.avi, *.mp4
    Write-Host ("Found {0} videos." -f $videos.Count)
    foreach ($split in "train", "val") {
        foreach ($cls in "Fight", "NonFight") {
            $n = ($videos | Where-Object { $_.FullName -match "\\$split\\$cls\\" }).Count
            Write-Host ("  {0}/{1}: {2}" -f $split, $cls, $n)
        }
    }

    Write-Host "== 3/4 Train on the GPU (accuracy is printed after every epoch) =="
    Set-Location $Backend
    & $Python manage.py train-fight-model --data $Extract --pretrained-backbone --device cuda:0 --workers 1 --batch-size 8 --activate
    $code = $LASTEXITCODE

    Write-Host "== 4/4 Result =="
    if ($code -eq 0) {
        Write-Host "Model trained and activated in backend\.env. Restart the backend to use it."
    } elseif ($code -eq 2) {
        Write-Host "Model trained but NOT activated (validation F1 below 0.75). The motion detector stays in use."
    } else {
        Write-Host "Training failed (exit code $code). See the messages above and $Log."
    }
} catch {
    Write-Host "ERROR: $_"
} finally {
    Stop-Transcript | Out-Null
    Write-Host ""
    Read-Host "Finished. Press Enter to close this window"
}
