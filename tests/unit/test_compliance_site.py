"""Guard the public Sage OAuth compliance site and its Google disclosures."""

from pathlib import Path


SITE_ROOT = Path(__file__).parents[2] / "site"
PUBLIC_ORIGIN = "https://sage.hrudainirmal.in"


def readSiteFile(relativePath: str) -> str:
    """Return one tracked site file as UTF-8 text."""
    return (SITE_ROOT / relativePath).read_text(encoding="utf-8")


def testComplianceSitePublishesCompleteLinkedPages():
    """The homepage, privacy policy, and terms remain mutually reachable."""
    expectedPages = {
        "index.html": PUBLIC_ORIGIN,
        "privacy.html": f"{PUBLIC_ORIGIN}/privacy",
        "terms.html": f"{PUBLIC_ORIGIN}/terms",
    }

    for relativePath, canonicalUrl in expectedPages.items():
        pageHtml = readSiteFile(relativePath)
        assert f'<link rel="canonical" href="{canonicalUrl}">' in pageHtml
        assert 'href="/privacy"' in pageHtml
        assert 'href="/terms"' in pageHtml
        assert "TODO" not in pageHtml
        assert "PLACEHOLDER" not in pageHtml


def testPrivacyPolicyDisclosesGoogleDataUseAndLimitedUse():
    """Google API access is described specifically instead of hidden in generic terms."""
    privacyHtml = readSiteFile("privacy.html")

    assert "Gmail" in privacyHtml
    assert "Google Calendar" in privacyHtml
    assert "Google Drive" in privacyHtml
    assert "Google API Services User Data Policy" in privacyHtml
    assert "Limited Use requirements" in privacyHtml
    assert "does not sell" in privacyHtml
    assert "hrudainirmalwork@gmail.com" in privacyHtml


def testStaticSiteHasNoTrackingOrRemoteScriptDependencies():
    """The compliance site itself remains static and does not add analytics collection."""
    for relativePath in ("index.html", "privacy.html", "terms.html"):
        pageHtml = readSiteFile(relativePath)
        assert "<script" not in pageHtml
        assert "https://www.googletagmanager.com" not in pageHtml
        assert "analytics" not in pageHtml.lower()

    vercelConfig = readSiteFile("vercel.json")
    assert '"cleanUrls": true' in vercelConfig
    assert '"X-Content-Type-Options"' in vercelConfig
