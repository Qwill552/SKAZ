param([Parameter(Mandatory=$true)][string]$Png)
# Input: transparent 512x512 browser rendering of the unchanged skaz.svg.
# Build-time only. End users receive the generated ICO in the release archive.
. "$PSScriptRoot\common.ps1"
Add-Type -AssemblyName System.Drawing
$Source = [Drawing.Image]::FromFile([IO.Path]::GetFullPath($Png))
$Sizes = @(16,20,24,32,48,256)
$Images = @()
try {
    foreach ($Size in $Sizes) {
        $Bitmap = New-Object Drawing.Bitmap($Size, $Size)
        $Graphics = [Drawing.Graphics]::FromImage($Bitmap)
        $Graphics.CompositingMode = [Drawing.Drawing2D.CompositingMode]::SourceCopy
        $Graphics.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $Graphics.PixelOffsetMode = [Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $Graphics.DrawImage($Source, 0, 0, $Size, $Size)
        $Stream = New-Object IO.MemoryStream
        if ($Size -eq 256) {
            $Bitmap.Save($Stream, [Drawing.Imaging.ImageFormat]::Png)
        } else {
            # Small PNG-only frames render incorrectly in some Windows/GDI icon
            # consumers. Use conventional 32-bit DIB + AND mask for tray sizes.
            $Dib = New-Object IO.BinaryWriter($Stream)
            $MaskStride = [int]([Math]::Ceiling($Size / 32.0) * 4)
            $Dib.Write([uint32]40); $Dib.Write([int32]$Size); $Dib.Write([int32]($Size * 2))
            $Dib.Write([uint16]1); $Dib.Write([uint16]32); $Dib.Write([uint32]0)
            $Dib.Write([uint32]($Size * $Size * 4 + $MaskStride * $Size))
            foreach ($Zero in 1..4) { $Dib.Write([uint32]0) }
            for ($Y=$Size-1; $Y -ge 0; $Y--) {
                for ($X=0; $X -lt $Size; $X++) {
                    $Pixel = $Bitmap.GetPixel($X,$Y)
                    $Dib.Write([byte]$Pixel.B); $Dib.Write([byte]$Pixel.G)
                    $Dib.Write([byte]$Pixel.R); $Dib.Write([byte]$Pixel.A)
                }
            }
            for ($Y=$Size-1; $Y -ge 0; $Y--) {
                $Mask = New-Object byte[] $MaskStride
                for ($X=0; $X -lt $Size; $X++) {
                    if ($Bitmap.GetPixel($X,$Y).A -eq 0) {
                        $Index = [int][Math]::Floor($X / 8.0)
                        $Mask[$Index] = $Mask[$Index] -bor (128 -shr ($X % 8))
                    }
                }
                $Dib.Write([byte[]]$Mask)
            }
            $Dib.Flush()
        }
        $Images += ,$Stream.ToArray()
        $Stream.Dispose(); $Graphics.Dispose(); $Bitmap.Dispose()
    }
    $File = [IO.File]::Create((Join-Path $PSScriptRoot 'skaz.ico'))
    $Writer = New-Object IO.BinaryWriter($File)
    try {
        $Writer.Write([uint16]0); $Writer.Write([uint16]1); $Writer.Write([uint16]$Sizes.Count)
        $Offset = 6 + 16 * $Sizes.Count
        for ($Index=0; $Index -lt $Sizes.Count; $Index++) {
            $Dimension = $Sizes[$Index] % 256
            $Writer.Write([byte]$Dimension); $Writer.Write([byte]$Dimension)
            $Writer.Write([byte]0); $Writer.Write([byte]0)
            $Writer.Write([uint16]1); $Writer.Write([uint16]32)
            $Writer.Write([uint32]$Images[$Index].Length); $Writer.Write([uint32]$Offset)
            $Offset += $Images[$Index].Length
        }
        foreach ($Bytes in $Images) { $Writer.Write([byte[]]$Bytes) }
    } finally { $Writer.Dispose(); $File.Dispose() }
} finally { $Source.Dispose() }
