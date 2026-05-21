import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, of, delay } from 'rxjs';
import { environment } from '../../../environments/environment';
import {
  MoodleCoursesData,
  MoodleCourseInfo,
  MoodleCourseStructure,
  FileParsedContent,
} from '../../interfaces/chatbot-i';

export interface UpdateCoursesResponse {
  message: string;
  chatbot_id: string;
  courses_added: string[];
  courses_removed: string[];
  total_added: number;
  total_removed: number;
  current_courses: string[];
  total_courses: number;
  reindexing: boolean;
  reindex_error?: string;
}

@Injectable({
  providedIn: 'root',
})
export class MoodleCoursesService {
  private http = inject(HttpClient);

  getMoodleCourses(chatbotId: string): Observable<MoodleCoursesData> {

    return this.http.get<MoodleCoursesData>(
      `/api/v2/chatbots/${chatbotId}/moodle-courses`
    );
  }

  updateCourseSelection(
    chatbotId: string,
    selectionKeys: string[]
  ): Observable<UpdateCoursesResponse> {
    // Selection key format: "course:course_id".
    const courseIds = selectionKeys.map((key) => {
      const parts = key.split(':');
      return parts[parts.length - 1];
    });


    return this.http.patch<UpdateCoursesResponse>(
      `/api/v2/chatbots/${chatbotId}/moodle-courses`,
      {
        course_ids: courseIds,
      }
    );
  }

  getCourseStructure(
    chatbotId: string,
    courseId: string
  ): Observable<MoodleCourseStructure> {
    return this.http.get<MoodleCourseStructure>(
      `/api/v2/chatbots/${chatbotId}/moodle-courses/${courseId}/structure`
    );
  }

  getMoodleParsedContent(
    chatbotId: string,
    courseId: string,
    opts: { activityId?: string; fileId?: string; sectionId?: string }
  ): Observable<FileParsedContent> {
    const params: Record<string, string> = {};
    if (opts.activityId) params['activity_id'] = opts.activityId;
    if (opts.fileId) params['file_id'] = opts.fileId;
    if (opts.sectionId) params['section_id'] = opts.sectionId;

    return this.http.get<FileParsedContent>(
      `/api/v2/chatbots/${chatbotId}/moodle-content/${courseId}/parsed`,
      { params }
    );
  }

}
