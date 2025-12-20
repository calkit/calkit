import React, { useCallback, useMemo, useState } from 'react';
import { ReactWidget } from '@jupyterlab/apputils';

interface SectionItem {
  id: string;
  label: string;
}

/**
 * A sidebar component for Calkit JupyterLab extension.
 * Displays sections for environments, pipeline stages, notebooks, figures,
 * datasets, questions, history, publications, notes, and models.
 */
export const CalkitSidebar: React.FC = () => {
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    () => new Set(['environments', 'notebooks'])
  );

  const toggleSection = useCallback((sectionId: string) => {
    setExpandedSections(prev => {
      const next = new Set(prev);
      if (next.has(sectionId)) {
        next.delete(sectionId);
      } else {
        next.add(sectionId);
      }
      return next;
    });
  }, []);

  const mockData = useMemo<Record<string, SectionItem[]>>(
    () => ({
      environments: [
        { id: 'env2', label: 'Python 3.10' },
        { id: 'env3', label: 'R Environment' }
      ],
      pipelineStages: [
        { id: 'stage1', label: 'Data Collection' },
        { id: 'stage2', label: 'Processing' },
        { id: 'stage3', label: 'Analysis' },
        { id: 'stage4', label: 'Visualization' }
      ],
      notebooks: [
        { id: 'nb1', label: 'Analysis.ipynb' },
        { id: 'nb2', label: 'Preprocessing.ipynb' }
      ],
      figures: [
        { id: 'fig1', label: 'distribution_plot.png' },
        { id: 'fig2', label: 'correlation_matrix.pdf' }
      ],
      datasets: [
        { id: 'ds1', label: 'raw_data.csv' },
        { id: 'ds2', label: 'processed_data.parquet' }
      ],
      questions: [
        { id: 'q1', label: 'What are the outliers?' },
        { id: 'q2', label: 'How significant is the correlation?' }
      ],
      history: [
        { id: 'h1', label: 'feat: Add analysis module' },
        { id: 'h2', label: 'fix: Update data pipeline' },
        { id: 'h3', label: 'docs: Update README' }
      ],
      publications: [
        { id: 'pub1', label: 'Nature 2024 - "Novel Approach..."' },
        { id: 'pub2', label: 'ArXiv 2023 - "Preliminary Results"' }
      ],
      notes: [
        { id: 'note1', label: 'Check data quality' },
        { id: 'note2', label: 'Follow up on edge cases' }
      ],
      models: [
        { id: 'model1', label: 'Linear Regression v1' },
        { id: 'model2', label: 'Neural Network v2' }
      ]
    }),
    []
  );

  const renderSection = useCallback(
    (sectionId: string, sectionLabel: string, icon: string) => {
      const isExpanded = expandedSections.has(sectionId);
      const items = mockData[sectionId] || [];

      return (
        <div key={sectionId} className="calkit-sidebar-section">
          <div
            className="calkit-sidebar-section-header"
            onClick={() => toggleSection(sectionId)}
          >
            <span className="calkit-sidebar-section-icon">
              {isExpanded ? '▼' : '▶'}
            </span>
            <span className="calkit-sidebar-section-label">{icon}</span>
            <span className="calkit-sidebar-section-title">{sectionLabel}</span>
            <span className="calkit-sidebar-section-count">
              {items.length > 0 && `(${items.length})`}
            </span>
          </div>
          {isExpanded && items.length > 0 && (
            <div className="calkit-sidebar-section-content">
              {items.map(item => (
                <div key={item.id} className="calkit-sidebar-item">
                  <span className="calkit-sidebar-item-label">
                    {item.label}
                  </span>
                </div>
              ))}
            </div>
          )}
          {isExpanded && items.length === 0 && (
            <div className="calkit-sidebar-section-empty">No items found</div>
          )}
        </div>
      );
    },
    [expandedSections, mockData, toggleSection]
  );

  return (
    <div className="calkit-sidebar">
      <div className="calkit-sidebar-header">
        <h2>Calkit</h2>
      </div>
      <div className="calkit-sidebar-content">
        {renderSection('environments', 'Environments', '⚙️')}
        {renderSection('pipelineStages', 'Pipeline Stages', '🔄')}
        {renderSection('notebooks', 'Notebooks', '📓')}
        {renderSection('figures', 'Figures', '📊')}
        {renderSection('datasets', 'Datasets', '📁')}
        {renderSection('questions', 'Questions', '❓')}
        {renderSection('history', 'History (Git Commits)', '📜')}
        {renderSection('publications', 'Publications', '📚')}
        {renderSection('notes', 'Notes', '📝')}
        {renderSection('models', 'Models', '🤖')}
      </div>
    </div>
  );
};

/**
 * A widget for the Calkit sidebar.
 */
export class CalkitSidebarWidget extends ReactWidget {
  constructor() {
    super();
    this.addClass('calkit-sidebar-widget');
  }

  render() {
    return <CalkitSidebar />;
  }
}
