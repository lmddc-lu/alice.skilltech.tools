import {
  Component,
  ChangeDetectionStrategy,
  signal,
  input,
  output,
  inject,
  effect,
  DestroyRef,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MoodleCoursesService } from '../../../../services/courses/moodle-courses.service';
import {
  MoodleCourseInfo,
  MoodleCourseStructure,
  MoodleActivity,
} from '../../../../interfaces/chatbot-i';
import { TranslatePipe, TranslateService } from '@ngx-translate/core';
import { parseMlang } from '../../../../core/mlang';
import { ContentBrowserComponent, TreeNode, PreviewState } from '../content-browser/content-browser.component';

@Component({
  selector: 'app-moodle-content-browser',
  imports: [ContentBrowserComponent, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './moodle-content-browser.component.html',
})
export class MoodleContentBrowserComponent {
  private moodleService = inject(MoodleCoursesService);
  private translate = inject(TranslateService);
  private destroyRef = inject(DestroyRef);

  chatbotId = input.required<string>();
  isOpen = input<boolean>(false);
  linkedCourses = input<MoodleCourseInfo[]>([]);

  close = output<void>();

  treeNodes = signal<TreeNode[]>([]);
  loadingStructure = signal(false);
  loadedCourses = signal<Set<string>>(new Set());
  private courseStructures = new Map<string, MoodleCourseStructure>();

  preview = signal<PreviewState>({ type: 'idle' });

  constructor() {
    effect(() => {
      if (this.isOpen()) {
        this.initTree();
      }
    });

    this.translate.onLangChange
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.rebuildTreeForLang());
  }

  private mlang(value: string): string {
    const lang =
      this.translate.getCurrentLang() ||
      this.translate.getFallbackLang() ||
      'en';
    return parseMlang(value, lang);
  }

  private rebuildTreeForLang(): void {
    const expanded = new Set<string>();
    const collect = (nodes: TreeNode[]) => {
      for (const n of nodes) {
        if (n.expanded) expanded.add(n.value);
        if (n.children) collect(n.children);
      }
    };
    collect(this.treeNodes());

    const courses = this.linkedCourses();
    this.treeNodes.set(
      courses.map((course) => {
        const structure = this.courseStructures.get(course.course_id);
        const children = structure ? this.buildSectionNodes(structure, expanded) : [];
        return {
          name: this.mlang(course.course_name),
          value: `course:${course.course_id}`,
          icon: '/icons/logo_moodle.svg',
          type: 'course',
          meta: this.mlang(course.category),
          data: { courseId: course.course_id },
          children,
          expanded: expanded.has(`course:${course.course_id}`),
        };
      })
    );
  }

  initTree(): void {
    const courses = this.linkedCourses();
    this.treeNodes.set(
      courses.map((course) => ({
        name: this.mlang(course.course_name),
        value: `course:${course.course_id}`,
        icon: '/icons/logo_moodle.svg',
        type: 'course',
        meta: this.mlang(course.category),
        data: { courseId: course.course_id },
        children: [],
        expanded: false,
      }))
    );
    this.loadedCourses.set(new Set());
    this.courseStructures.clear();
    this.preview.set({ type: 'idle' });
  }

  onNodeClick(node: TreeNode): void {
    if (node.type === 'course') {
      this.loadCourseIfNeeded(node);
      this.preview.set({ type: 'idle' });
    } else if (node.type === 'section') {
      // Sections are folders; expand/collapse only.
      this.preview.set({ type: 'idle' });
    } else if (node.type === 'section-summary') {
      this.loadSectionContent(node);
    } else if (node.type === 'activity') {
      this.loadActivityContent(node);
    } else if (node.type === 'file') {
      this.loadFileContent(node);
    }
  }

  private loadCourseIfNeeded(node: TreeNode): void {
    const courseId = node.data?.['courseId'] as string;
    if (this.loadedCourses().has(courseId)) return;

    this.loadingStructure.set(true);

    this.moodleService
      .getCourseStructure(this.chatbotId(), courseId)
      .subscribe({
        next: (structure) => {
          this.loadedCourses.update((s) => new Set([...s, courseId]));
          this.courseStructures.set(courseId, structure);
          this.treeNodes.update((nodes) =>
            nodes.map((n) =>
              n.data?.['courseId'] === courseId
                ? { ...n, children: this.buildSectionNodes(structure), expanded: true }
                : n
            )
          );
          this.loadingStructure.set(false);
        },
        error: () => {
          this.loadingStructure.set(false);
        },
      });
  }

  private buildSectionNodes(
    structure: MoodleCourseStructure,
    expanded?: Set<string>
  ): TreeNode[] {
    return structure.sections.map((section) => {
      const activityNodes = section.activities.map((activity) =>
        this.buildActivityNode(structure.course_id, activity, expanded)
      );

      const children: TreeNode[] = [];
      if (section.has_indexed_content) {
        children.push({
          name: 'Section summary',
          value: `section-summary:${structure.course_id}:${section.id}`,
          icon: '/icons/file.svg',
          type: 'section-summary',
          data: {
            courseId: structure.course_id,
            sectionId: section.id,
          },
        });
      }
      children.push(...activityNodes);

      const value = `section:${structure.course_id}:${section.section_number}`;
      return {
        name: this.mlang(section.name),
        value,
        icon: '/icons/grid.svg',
        type: 'section',
        data: {
          courseId: structure.course_id,
          sectionId: section.id,
        },
        children: children.length > 0 ? children : undefined,
        expanded: expanded?.has(value) ?? false,
      };
    });
  }

  private buildActivityNode(
    courseId: string,
    activity: MoodleActivity,
    expanded?: Set<string>
  ): TreeNode {
    const moodleUrl = this.getMoodleActivityUrl(courseId, activity);
    const children: TreeNode[] = activity.files.map((file) => ({
      name: file.filename,
      value: `file:${courseId}:${activity.id}:${file.id}`,
      icon: this.getFileIcon(file.mimetype, file.filename),
      type: 'file',
      meta: this.formatFileSize(file.filesize),
      data: {
        courseId,
        activityId: activity.id,
        fileId: file.id,
        moodleUrl,
      },
    }));

    const value = `activity:${courseId}:${activity.id}`;
    return {
      name: this.mlang(activity.name),
      value,
      icon: this.getActivityIcon(activity.type),
      type: 'activity',
      meta: this.mlang(activity.type),
      data: {
        courseId,
        activityId: activity.id,
        moodleUrl,
        hasIndexedContent: activity.has_indexed_content,
      },
      children: children.length > 0 ? children : undefined,
      expanded: expanded?.has(value) ?? false,
    };
  }

  private loadSectionContent(node: TreeNode): void {
    this.preview.set({ type: 'loading', fileName: node.name });

    this.moodleService
      .getMoodleParsedContent(this.chatbotId(), node.data?.['courseId'] as string, {
        sectionId: node.data?.['sectionId'] as string,
      })
      .subscribe({
        next: (result) => {
          this.preview.set({
            type: 'content',
            fileName: node.name,
            content: result.content,
            totalChunks: result.total_chunks,
            externalUrl: null,
          });
        },
        error: (err) => {
          if (err.status === 404) {
            this.preview.set({ type: 'no-content', fileName: node.name });
          } else {
            this.preview.set({ type: 'error', fileName: node.name });
          }
        },
      });
  }

  private loadActivityContent(node: TreeNode): void {
    if (!node.data?.['hasIndexedContent']) {
      this.preview.set({ type: 'no-content', fileName: node.name });
      return;
    }

    this.preview.set({ type: 'loading', fileName: node.name });

    this.moodleService
      .getMoodleParsedContent(this.chatbotId(), node.data?.['courseId'] as string, {
        activityId: node.data?.['activityId'] as string,
      })
      .subscribe({
        next: (result) => {
          this.preview.set({
            type: 'content',
            fileName: node.name,
            content: result.content,
            totalChunks: result.total_chunks,
            externalUrl: (node.data?.['moodleUrl'] as string) || null,
          });
        },
        error: (err) => {
          if (err.status === 404) {
            this.preview.set({ type: 'no-content', fileName: node.name });
          } else {
            this.preview.set({ type: 'error', fileName: node.name });
          }
        },
      });
  }

  private loadFileContent(node: TreeNode): void {
    this.preview.set({ type: 'loading', fileName: node.name });

    this.moodleService
      .getMoodleParsedContent(this.chatbotId(), node.data?.['courseId'] as string, {
        activityId: node.data?.['activityId'] as string,
        fileId: node.data?.['fileId'] as string,
      })
      .subscribe({
        next: (result) => {
          this.preview.set({
            type: 'content',
            fileName: node.name,
            content: result.content,
            totalChunks: result.total_chunks,
            externalUrl: (node.data?.['moodleUrl'] as string) || null,
          });
        },
        error: (err) => {
          if (err.status === 404) {
            this.preview.set({ type: 'no-content', fileName: node.name });
          } else {
            this.preview.set({ type: 'error', fileName: node.name });
          }
        },
      });
  }

  private getMoodleActivityUrl(courseId: string, activity: MoodleActivity): string {
    const course = this.linkedCourses().find((c) => c.course_id === courseId);
    if (!course?.moodle_domain) return '';
    const domain = course.moodle_domain.replace(/\/+$/, '');
    return `${domain}/mod/${activity.type}/view.php?id=${activity.id}`;
  }

  getFileIcon(mimetype: string, filename: string): string {
    if (mimetype) {
      if (mimetype.includes('pdf')) return '/icons/file.svg';
      if (mimetype.includes('presentation') || mimetype.includes('powerpoint'))
        return '/icons/monitor.svg';
      if (mimetype.includes('spreadsheet') || mimetype.includes('excel'))
        return '/icons/grid.svg';
      if (mimetype.includes('word') || mimetype.includes('document'))
        return '/icons/file.svg';
      if (mimetype.startsWith('image/')) return '/icons/eye.svg';
      if (mimetype.includes('zip') || mimetype.includes('scorm'))
        return '/icons/package.svg';
    }
    const ext = filename.split('.').pop()?.toLowerCase() ?? '';
    if (['pdf'].includes(ext)) return '/icons/file.svg';
    if (['pptx', 'ppt'].includes(ext)) return '/icons/monitor.svg';
    if (['xlsx', 'xls', 'csv'].includes(ext)) return '/icons/grid.svg';
    if (['zip', 'scorm'].includes(ext)) return '/icons/package.svg';
    if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'].includes(ext))
      return '/icons/eye.svg';
    return '/icons/file.svg';
  }

  getActivityIcon(type: string): string {
    const iconMap: Record<string, string> = {
      resource: '/icons/file.svg',
      forum: '/icons/message-circle.svg',
      scorm: '/icons/monitor.svg',
      glossary: '/icons/book-open.svg',
      book: '/icons/book.svg',
      wiki: '/icons/edit.svg',
      page: '/icons/file.svg',
      url: '/icons/external-link.svg',
      label: '/icons/info.svg',
    };
    return iconMap[type] || '/icons/file.svg';
  }

  formatFileSize(bytes: number): string {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }
}
