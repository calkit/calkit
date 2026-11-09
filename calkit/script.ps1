    try {
        Write-Host "Right before GetActiveObject"
        $word = [System.Runtime.InteropServices.Marshal]::GetActiveObject(
            "Word.Application"
        )
        Write-Host "After GetActiveObject"
    }
    catch {
        Write-Host "Word not already running, attempting to open a new instance"
        $word = New-Object -ComObject Word.Application
        $started = $true
        Write-Host "Opened a new instance"
    }

    $word.DisplayAlerts = 0

    try {
        # Open PDF (ConfirmConversions = False).
        Write-Host "In the opening try block"
        Write-Host "Word instance: $($null -ne $word)"
        Write-Host "Documents collection: $($null -ne $word.Documents)"
        Write-Host "Opening: $PdfPath"

        $doc = $word.Documents.Open(
            $PdfPath,
            $false  # ConfirmConversions
        )
        Write-Host "doc is null: $($null -eq $doc)"
        Write-Host "doc type: $($doc.GetType().FullName)"
        Write-Host "Opened doc"

        # wdNoProtection = -1
        if ($doc.ProtectionType -ne -1) {
            Write-Host "Unprotecting"
            $doc.Unprotect()
        }

        $doc.Final = $false
        $doc.ReadOnlyRecommended = $false

        # wdFormatXMLDocument = 12
        Write-Host "Saving doc"
        $doc.SaveAs2($OutputPath, 12)
        Write-Host "Saved doc"

    }
    finally {
        if ($null -ne $doc) {
            $doc.Close($false)
            [System.Runtime.InteropServices.Marshal]::ReleaseComObject($doc) |
                Out-Null
        }
    }

    # Match the original behavior: only quit Word if we started it.
    if ($started) {
        $word.Quit()
    }

    exit 0
