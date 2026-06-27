from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

MATRIX_PATTERNS = (
    "support-matrix",
    "compatibility-matrix",
    "product-compatibility",
    "release-matrix",
    "supported-services-matrix",
    "feature-support-matrix",
    "client-server-compatibility",
    "api-compatibility",
)

PRODUCT_NAMES: dict[str, str] = {
    "runtime": "Cloudera Runtime",
    "cdp-private-cloud-base": "CDP Private Cloud Base",
    "cdp-private-cloud": "CDP Private Cloud",
    "cdp-private-cloud-data-services": "CDP Private Cloud Data Services",
    "cdp-private-cloud-upgrade": "CDP Private Cloud Upgrade",
    "cdp-public-cloud": "CDP Public Cloud",
    "cdp-public-cloud-patterns": "CDP Public Cloud Patterns",
    "cdp-reference-architectures": "CDP Reference Architectures",
    "cfm": "Cloudera Flow Management (NiFi)",
    "cfm-operator": "CFM Operator",
    "cdf-datahub": "CDF Data Hub",
    "csa": "Cloudera Streaming Analytics",
    "csa-operator": "CSA Operator",
    "csm-operator": "CSM Operator",
    "csp-ce": "Cloudera Streaming Platform CE",
    "cdsw": "Cloudera Data Science Workbench",
    "cdw-runtime": "CDW Runtime",
    "data-warehouse": "Cloudera Data Warehouse",
    "data-engineering": "Cloudera Data Engineering (CDE)",
    "data-catalog": "Cloudera Data Catalog",
    "data-hub": "Cloudera Data Hub",
    "data-visualization": "Cloudera Data Visualization",
    "dataflow": "Cloudera DataFlow",
    "machine-learning": "Cloudera Machine Learning (CML)",
    "management-console": "Cloudera Management Console",
    "observability": "Cloudera Observability",
    "operational-database": "Cloudera Operational Database (COD)",
    "replication-manager": "Cloudera Replication Manager",
    "storage": "Cloudera Storage",
    "hybrid-cloud": "Cloudera Hybrid Cloud",
    "cem": "Cloudera Edge Management",
    "octopai": "Octopai",
    "cloudera-account-360": "Cloudera Account 360",
}

SERVICE_KEYWORDS: dict[str, str] = {
    "impala": "Impala",
    "hive": "Hive",
    "spark": "Spark",
    "hbase": "HBase",
    "hdfs": "HDFS",
    "yarn": "YARN",
    "ranger": "Ranger",
    "atlas": "Atlas",
    "knox": "Knox",
    "kafka": "Kafka",
    "nifi": "NiFi",
    "oozie": "Oozie",
    "hue": "Hue",
    "zookeeper": "ZooKeeper",
    "solr": "Solr",
    "flink": "Flink",
    "iceberg": "Iceberg",
    "kudu": "Kudu",
    "ozone": "Ozone",
    "phoenix": "Phoenix",
    "schema-registry": "Schema Registry",
    "sqoop": "Sqoop",
    "tez": "Tez",
    "livy": "Livy",
    "zeppelin": "Zeppelin",
    "cm": "Cloudera Manager",
    "cloudera-manager": "Cloudera Manager",
    "data-hub": "Data Hub",
    "datalake": "Data Lake",
    "cde": "Cloudera Data Engineering",
    "cdw": "Cloudera Data Warehouse",
    "cml": "Cloudera Machine Learning",
    "cdp": "Cloudera Data Platform",
    "atscale": "AtScale",
    "longhorn": "Longhorn",
    "etcd": "etcd",
    "vault": "Vault",
    "ssl": "SSL/TLS",
    "truststore": "Truststore",
    "replication": "Replication",
    "balancer": "HDFS Balancer",
    "admission-control": "Admission Control",
    "provenance": "Provenance",
    "erasure-coding": "Erasure Coding",
    "autotls": "AutoTLS",
    "ecs": "ECS",
    "cdsw": "CDSW",
}


@dataclass
class ClouderaMetadata:
    product: str
    product_name: str
    version: str
    service: str
    doc_type: str
    is_support_matrix: bool = False

    def context_header(self) -> str:
        parts = [
            f"Product: {self.product_name or self.product}",
            f"Version: {self.version or 'unknown'}",
        ]
        if self.service:
            parts.append(f"Service: {self.service}")
        if self.doc_type:
            parts.append(f"DocType: {self.doc_type}")
        return " | ".join(parts)


def parse_cloudera_url(url: str) -> ClouderaMetadata:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]

    product = parts[0] if parts else ""
    version = parts[1] if len(parts) > 1 else ""
    if version in {"topics", "administration", "release-notes", "start-base-on-premises"}:
        version = "latest"

    service = _detect_service_from_path(parts)
    doc_type = _detect_doc_type(url, parts)
    is_matrix = doc_type == "support-matrix"

    return ClouderaMetadata(
        product=product,
        product_name=PRODUCT_NAMES.get(product, product.replace("-", " ").title()),
        version=version,
        service=service,
        doc_type=doc_type,
        is_support_matrix=is_matrix,
    )


def parse_local_metadata(title: str, source_url: str) -> ClouderaMetadata:
    combined = f"{title} {source_url}".lower()
    service = _detect_service_from_text(combined)
    doc_type = "sop-mop"
    if "[mop]" in combined:
        doc_type = "mop"
    elif "[sop]" in combined:
        doc_type = "sop"
    elif "[rca]" in combined:
        doc_type = "rca"
    elif "[wri]" in combined or "working instruction" in combined:
        doc_type = "working-instruction"

    return ClouderaMetadata(
        product="internal",
        product_name="Internal Runbook (BRI)",
        version="internal",
        service=service,
        doc_type=doc_type,
        is_support_matrix=False,
    )


def url_fetch_priority(url: str) -> tuple[int, str]:
    meta = parse_cloudera_url(url)
    if meta.is_support_matrix:
        return (0, url)
    if meta.doc_type == "release-notes":
        return (1, url)
    if meta.doc_type == "overview":
        return (2, url)
    return (3, url)


def is_support_matrix_url(url: str) -> bool:
    lower = url.lower()
    return any(pattern in lower for pattern in MATRIX_PATTERNS)


def _detect_service_from_path(parts: list[str]) -> str:
    for part in parts[2:]:
        normalized = part.lower()
        for keyword, name in SERVICE_KEYWORDS.items():
            if keyword in normalized:
                return name
    return ""


def _detect_service_from_text(text: str) -> str:
    for keyword, name in sorted(SERVICE_KEYWORDS.items(), key=lambda item: -len(item[0])):
        if keyword in text:
            return name
    return ""


def _detect_doc_type(url: str, parts: list[str]) -> str:
    lower = url.lower()
    if is_support_matrix_url(url):
        return "support-matrix"
    if "release-notes" in lower or "public-release-notes" in parts:
        return "release-notes"
    if "overview" in lower:
        return "overview"
    if "administration" in lower:
        return "administration"
    if "installation" in lower or "install" in lower:
        return "installation"
    if "upgrade" in lower:
        return "upgrade"
    if "security" in lower:
        return "security"
    if "troubleshoot" in lower:
        return "troubleshooting"
    return "guide"


def parse_sitemap_product_version(sitemap_url: str) -> tuple[str, str, str]:
    parsed = urlparse(sitemap_url)
    parts = [part for part in parsed.path.split("/") if part and part != "sitemap.xml"]
    product = parts[0] if parts else ""
    version = parts[1] if len(parts) > 1 else "latest"
    product_name = PRODUCT_NAMES.get(product, product.replace("-", " ").title())
    return product, version, product_name
