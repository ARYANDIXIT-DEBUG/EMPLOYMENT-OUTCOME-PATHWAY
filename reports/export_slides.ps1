$pptxPath = (Resolve-Path "submission\Turkey_ISKUR_CA_presentation_v4.pptx").Path
$outputDir = Join-Path (Resolve-Path "reports").Path "presentation_slides"
if (!(Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}

$ppt = New-Object -ComObject PowerPoint.Application
try {
    # Open(FileName, ReadOnly, Untitled, WithWindow)
    $presentation = $ppt.Presentations.Open($pptxPath, 1, 0, 0)
    $slideCount = $presentation.Slides.Count
    Write-Output "Slide count: $slideCount"
    for ($i = 1; $i -le $slideCount; $i++) {
        $slide = $presentation.Slides.Item($i)
        $slideImg = Join-Path $outputDir "slide_$i.png"
        $slide.Export($slideImg, "PNG", 1920, 1080)
        Write-Output "Exported slide $i to $slideImg"
    }
    $presentation.Close()
}
finally {
    $ppt.Quit()
    [System.Runtime.Interopservices.Marshal]::ReleaseComObject($ppt) | Out-Null
}

