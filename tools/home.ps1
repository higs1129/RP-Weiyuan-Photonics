function Resolve-RpWeiyuanHome {
    if ($env:RP_WEIYUAN_HOME) {
        if (![IO.Path]::IsPathRooted($env:RP_WEIYUAN_HOME)) { throw "RP_WEIYUAN_HOME must be an absolute path." }
        return $env:RP_WEIYUAN_HOME
    }
    return (Join-Path $env:LOCALAPPDATA "RP-Weiyuan-Photonics\standalone")
}
