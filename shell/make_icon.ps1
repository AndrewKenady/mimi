<#
.SYNOPSIS
    Generates shell\mimi.ico: the Mimi "Well" - a luminous cyan orb glowing up out of a
    deep-navy rounded tile - at 16, 24, 32, 48, 64, 128 and 256 px.

.DESCRIPTION
    Pure System.Drawing (GDI+), no external tools. Every size is drawn at 4x and filtered down,
    and small sizes get a simplified drawing (bigger orb, no hairline rings) so they stay crisp
    in the tray and the taskbar. Frames up to 128 px are stored as 32-bit DIBs with an AND mask
    for maximum compatibility; the 256 px frame is PNG-compressed, as Windows expects.

.PARAMETER OutFile
    Where to write the .ico. Default: mimi.ico next to this script.

.PARAMETER PreviewPng
    Optional: also write a contact sheet of all sizes on dark and light backgrounds.
#>
[CmdletBinding()]
param(
    [string]$OutFile,
    [string]$PreviewPng
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

# ($PSScriptRoot is not available inside param() defaults on PowerShell 5.1.)
if (-not $OutFile) { $OutFile = Join-Path $PSScriptRoot 'mimi.ico' }

$Sizes = @(16, 24, 32, 48, 64, 128, 256)

function New-Argb([int]$a, [int]$r, [int]$g, [int]$b) { [System.Drawing.Color]::FromArgb($a, $r, $g, $b) }

function New-RoundedRect([float]$x, [float]$y, [float]$w, [float]$h, [float]$radius) {
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $d = 2 * $radius
    $path.AddArc($x, $y, $d, $d, 180, 90)
    $path.AddArc($x + $w - $d, $y, $d, $d, 270, 90)
    $path.AddArc($x + $w - $d, $y + $h - $d, $d, $d, 0, 90)
    $path.AddArc($x, $y + $h - $d, $d, $d, 90, 90)
    $path.CloseFigure()
    return , $path
}

function New-Ellipse([float]$cx, [float]$cy, [float]$rx, [float]$ry) {
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddEllipse($cx - $rx, $cy - $ry, 2 * $rx, 2 * $ry)
    return , $path
}

# Radial gradient over an elliptical path. $Stops are @(position, color) pairs where position 0
# is the rim of the ellipse and 1 is its centre (GDI+ PathGradientBrush convention).
function New-RadialBrush($path, [System.Drawing.PointF]$center, [object[]]$stops) {
    $brush = New-Object System.Drawing.Drawing2D.PathGradientBrush($path)
    $brush.CenterPoint = $center
    $blend = New-Object System.Drawing.Drawing2D.ColorBlend($stops.Count)
    $blend.Positions = [float[]]@($stops | ForEach-Object { [float]$_[0] })
    $blend.Colors = [System.Drawing.Color[]]@($stops | ForEach-Object { $_[1] })
    $brush.InterpolationColors = $blend
    return , $brush
}

function New-IconFrame([int]$Size) {
    $ss = 4
    $S = [float]($Size * $ss)
    $canvas = New-Object System.Drawing.Bitmap([int]$S, [int]$S, [System.Drawing.Imaging.PixelFormat]::Format32bppPArgb)
    $g = [System.Drawing.Graphics]::FromImage($canvas)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $g.Clear([System.Drawing.Color]::Transparent)

    $tiny  = $Size -le 24      # tray / small taskbar: bold and simple
    $small = $Size -le 48      # no double rings, no rim light

    # --- the tile ------------------------------------------------------------------------------
    $margin = $S * $(if ($tiny) { 0.03 } else { 0.05 })
    $tileSize = $S - 2 * $margin
    $tile = New-RoundedRect $margin $margin $tileSize $tileSize ($tileSize * 0.24)
    $fill = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
        (New-Object System.Drawing.PointF(0, $margin)), (New-Object System.Drawing.PointF(0, ($S - $margin))),
        (New-Argb 255 17 29 54), (New-Argb 255 5 8 16))
    $g.FillPath($fill, $tile)

    $cx = $S / 2
    $cy = $S / 2
    $orbR = $tileSize * $(if ($tiny) { 0.31 } elseif ($small) { 0.27 } else { 0.245 })

    # Faint light spilling up the walls of the well, clipped to the tile.
    $g.SetClip($tile)
    $spillR = $tileSize * 0.58
    $spill = New-Ellipse $cx $cy $spillR $spillR
    $spillBrush = New-RadialBrush $spill (New-Object System.Drawing.PointF($cx, $cy)) @(
        @(0.0, (New-Argb 0 20 110 190)), @(0.6, (New-Argb 26 24 140 210)), @(1.0, (New-Argb 80 36 180 230)))
    $g.FillPath($spillBrush, $spill)
    $g.ResetClip()

    # Hairline rim, brighter at the top, so the tile reads on dark taskbars too.
    $rimWidth = [Math]::Max($ss * 1.0, $S * 0.007)
    $inset = $margin + $rimWidth / 2
    $rimPath = New-RoundedRect $inset $inset ($S - 2 * $inset) ($S - 2 * $inset) (($S - 2 * $inset) * 0.24)
    $rimTop = if ($tiny) { 120 } else { 95 }
    $rimBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
        (New-Object System.Drawing.PointF(0, $margin)), (New-Object System.Drawing.PointF(0, ($S - $margin))),
        (New-Argb $rimTop 140 220 255), (New-Argb ([int]($rimTop * 0.35)) 110 190 255))
    $rimPen = New-Object System.Drawing.Pen($rimBrush, $rimWidth)
    $g.DrawPath($rimPen, $rimPath)

    # --- the glow and the ripples --------------------------------------------------------------
    $glowR = $orbR * $(if ($tiny) { 1.5 } else { 1.8 })
    $glow = New-Ellipse $cx $cy $glowR $glowR
    $glowBrush = New-RadialBrush $glow (New-Object System.Drawing.PointF($cx, $cy)) @(
        @(0.0, (New-Argb 0 40 190 255)), @(0.5, (New-Argb 60 50 205 255)),
        @(0.8, (New-Argb 175 80 222 255)), @(1.0, (New-Argb 235 140 240 255)))
    $g.FillPath($glowBrush, $glow)

    if (-not $tiny) {
        # (radius as a multiple of the orb radius, alpha, stroke width as a fraction of the canvas)
        if ($small) { $rings = @(, @(1.5, 70, 0.011)) } else { $rings = @(@(1.42, 75, 0.008), @(1.82, 34, 0.006)) }
        foreach ($ring in $rings) {
            $r = $orbR * $ring[0]
            $pen = New-Object System.Drawing.Pen((New-Argb $ring[1] 120 236 255), [Math]::Max($ss * 0.75, $S * $ring[2]))
            $g.DrawEllipse($pen, $cx - $r, $cy - $r, 2 * $r, 2 * $r)
            $pen.Dispose()
        }
    }

    # --- the orb ---------------------------------------------------------------------------------
    $orb = New-Ellipse $cx $cy $orbR $orbR
    $orbBrush = New-RadialBrush $orb (New-Object System.Drawing.PointF(($cx - 0.14 * $orbR), ($cy - 0.20 * $orbR))) @(
        @(0.00, (New-Argb 255 9 62 112)),
        @(0.18, (New-Argb 255 14 128 190)),
        @(0.45, (New-Argb 255 38 204 240)),
        @(0.72, (New-Argb 255 140 244 255)),
        @(0.90, (New-Argb 255 226 253 255)),
        @(1.00, (New-Argb 255 255 255 255)))
    $g.FillPath($orbBrush, $orb)

    if ($Size -ge 32) {
        # Specular highlight, top-left.
        $state = $g.Save()
        $g.TranslateTransform(($cx - 0.40 * $orbR), ($cy - 0.50 * $orbR))
        $g.RotateTransform(-35)
        $hl = New-Ellipse 0 0 (0.34 * $orbR) (0.19 * $orbR)
        $hlBrush = New-RadialBrush $hl (New-Object System.Drawing.PointF(0, 0)) @(
            @(0.0, (New-Argb 0 255 255 255)), @(1.0, (New-Argb 190 255 255 255)))
        $g.FillPath($hlBrush, $hl)
        $g.Restore($state)
    }
    $g.Dispose()

    # --- filter down to the target size ------------------------------------------------------------
    $frame = New-Object System.Drawing.Bitmap($Size, $Size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $fg = [System.Drawing.Graphics]::FromImage($frame)
    $fg.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $fg.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $fg.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $fg.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceCopy
    $attributes = New-Object System.Drawing.Imaging.ImageAttributes
    $attributes.SetWrapMode([System.Drawing.Drawing2D.WrapMode]::TileFlipXY)   # no dark fringe at the edges
    $fg.DrawImage($canvas, (New-Object System.Drawing.Rectangle(0, 0, $Size, $Size)), 0, 0, [int]$S, [int]$S,
        [System.Drawing.GraphicsUnit]::Pixel, $attributes)
    $fg.Dispose()
    $canvas.Dispose()
    return , $frame
}

# 32-bit BGRA DIB (bottom-up) followed by a 1-bpp AND mask, as stored inside .ico files.
function ConvertTo-DibBytes([System.Drawing.Bitmap]$bitmap) {
    $w = $bitmap.Width
    $h = $bitmap.Height
    $rect = New-Object System.Drawing.Rectangle(0, 0, $w, $h)
    $data = $bitmap.LockBits($rect, [System.Drawing.Imaging.ImageLockMode]::ReadOnly, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $stride = $data.Stride
    $pixels = New-Object byte[] ($stride * $h)
    [System.Runtime.InteropServices.Marshal]::Copy($data.Scan0, $pixels, 0, $pixels.Length)
    $bitmap.UnlockBits($data)

    $maskStride = [int]([Math]::Floor(($w + 31) / 32) * 4)
    $stream = New-Object System.IO.MemoryStream
    $writer = New-Object System.IO.BinaryWriter($stream)
    $writer.Write([int]40)                    # biSize
    $writer.Write([int]$w)                    # biWidth
    $writer.Write([int]($h * 2))              # biHeight: colour + mask
    $writer.Write([int16]1)                   # biPlanes
    $writer.Write([int16]32)                  # biBitCount
    $writer.Write([int]0)                     # biCompression = BI_RGB
    $writer.Write([int]($w * 4 * $h + $maskStride * $h))
    $writer.Write([int]0); $writer.Write([int]0); $writer.Write([int]0); $writer.Write([int]0)
    for ($y = $h - 1; $y -ge 0; $y--) { $writer.Write($pixels, $y * $stride, $w * 4) }
    for ($y = $h - 1; $y -ge 0; $y--) {
        $row = New-Object byte[] $maskStride
        for ($x = 0; $x -lt $w; $x++) {
            if ($pixels[$y * $stride + $x * 4 + 3] -eq 0) { $row[$x -shr 3] = $row[$x -shr 3] -bor (0x80 -shr ($x -band 7)) }
        }
        $writer.Write($row)
    }
    $writer.Flush()
    return , $stream.ToArray()
}

function ConvertTo-PngBytes([System.Drawing.Bitmap]$bitmap) {
    $stream = New-Object System.IO.MemoryStream
    $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
    return , $stream.ToArray()
}

# ---------------------------------------------------------------------------------------------
$frames = @{}
$images = New-Object System.Collections.ArrayList
foreach ($size in $Sizes) {
    $frame = New-IconFrame $size
    $frames[$size] = $frame
    if ($size -ge 256) { $bytes = ConvertTo-PngBytes $frame } else { $bytes = ConvertTo-DibBytes $frame }
    [void]$images.Add([pscustomobject]@{ Size = $size; Bytes = [byte[]]$bytes })
}

$out = New-Object System.IO.MemoryStream
$writer = New-Object System.IO.BinaryWriter($out)
$writer.Write([int16]0)                       # reserved
$writer.Write([int16]1)                       # type: icon
$writer.Write([int16]$images.Count)
$offset = 6 + 16 * $images.Count
foreach ($image in $images) {
    $dim = if ($image.Size -ge 256) { 0 } else { $image.Size }
    $writer.Write([byte]$dim)                 # width  (0 means 256)
    $writer.Write([byte]$dim)                 # height
    $writer.Write([byte]0)                    # palette size
    $writer.Write([byte]0)                    # reserved
    $writer.Write([int16]1)                   # colour planes
    $writer.Write([int16]32)                  # bits per pixel
    $writer.Write([int]$image.Bytes.Length)
    $writer.Write([int]$offset)
    $offset += $image.Bytes.Length
}
foreach ($image in $images) { $writer.Write([byte[]]$image.Bytes) }
$writer.Flush()
[System.IO.File]::WriteAllBytes($OutFile, $out.ToArray())
Write-Host ("Wrote {0} ({1:N0} bytes; sizes {2})" -f $OutFile, $out.Length, ($Sizes -join ', '))

if ($PreviewPng) {
    # Contact sheet: every size at 1x on a dark and a light strip, plus 4x zooms of the small ones.
    $sheetW = 16 + ($Sizes | Measure-Object -Sum).Sum + 16 * $Sizes.Count
    $zoomSizes = @(16, 24, 32)
    $zoomW = 16 + (($zoomSizes | ForEach-Object { $_ * 4 + 16 }) | Measure-Object -Sum).Sum
    $sheet = New-Object System.Drawing.Bitmap([int][Math]::Max($sheetW, $zoomW), [int](2 * (256 + 32) + 128 + 48))
    $sg = [System.Drawing.Graphics]::FromImage($sheet)
    $sg.Clear((New-Argb 255 32 32 32))
    $sg.FillRectangle((New-Object System.Drawing.SolidBrush((New-Argb 255 243 243 243))), 0, 288, $sheet.Width, 288)
    foreach ($row in @(0, 288)) {
        $x = 16
        foreach ($size in $Sizes) { $sg.DrawImageUnscaled($frames[$size], $x, $row + 16 + (256 - $size)); $x += $size + 16 }
    }
    $sg.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
    $sg.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
    $x = 16
    foreach ($size in $zoomSizes) {
        $sg.DrawImage($frames[$size], (New-Object System.Drawing.Rectangle($x, (576 + 16), ($size * 4), ($size * 4))))
        $x += $size * 4 + 16
    }
    $sg.Dispose()
    [System.IO.File]::WriteAllBytes($PreviewPng, (ConvertTo-PngBytes $sheet))   # GDI+ Save() dislikes long paths
    $sheet.Dispose()
    Write-Host "Wrote preview $PreviewPng"
}
foreach ($frame in $frames.Values) { $frame.Dispose() }
