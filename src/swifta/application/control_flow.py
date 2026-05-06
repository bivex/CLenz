"""Use cases for structured control flow diagrams."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from swifta.domain.ports import NassiDiagramRenderer, SourceRepository, SwiftControlFlowExtractor


@dataclass(frozen=True, slots=True)
class BuildNassiDiagramCommand:
    path: str


@dataclass(frozen=True, slots=True)
class BuildNassiDirectoryCommand:
    root_path: str


@dataclass(frozen=True, slots=True)
class NassiDiagramDocumentDTO:
    source_location: str
    function_count: int
    function_names: tuple[str, ...]
    html: str

    def to_dict(self) -> dict[str, object]:
        return {
            "source_location": self.source_location,
            "function_count": self.function_count,
            "function_names": list(self.function_names),
        }


@dataclass(frozen=True, slots=True)
class NassiDiagramBundleDTO:
    root_path: str
    document_count: int
    documents: tuple[NassiDiagramDocumentDTO, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "root_path": self.root_path,
            "document_count": self.document_count,
            "documents": [document.to_dict() for document in self.documents],
        }


@dataclass(slots=True)
class NassiDiagramService:
    source_repository: SourceRepository
    extractor: SwiftControlFlowExtractor
    renderer: NassiDiagramRenderer

    def build_file_diagram(self, command: BuildNassiDiagramCommand) -> NassiDiagramDocumentDTO:
        source_unit = self.source_repository.load_file(command.path)
        return self._build_document(source_unit)

    def build_directory_diagrams(self, command: BuildNassiDirectoryCommand) -> NassiDiagramBundleDTO:
        source_units = tuple(self.source_repository.list_swift_sources(command.root_path))
        documents = tuple(self._build_document(source_unit) for source_unit in source_units)
        return NassiDiagramBundleDTO(
            root_path=str(Path(command.root_path).expanduser().resolve()),
            document_count=len(documents),
            documents=documents,
        )

    def _build_document(self, source_unit) -> NassiDiagramDocumentDTO:
        diagram = self.extractor.extract(source_unit)
        return NassiDiagramDocumentDTO(
            source_location=diagram.source_location,
            function_count=len(diagram.functions),
            function_names=tuple(function.qualified_name for function in diagram.functions),
            html=self.renderer.render(diagram),
        )
